"""Safe Route Advisor (REQ-F-030, REQ-F-031, REQ-F-032).

Menerima titik asal, tujuan, dan waktu berangkat, lalu memeriksa apakah rute
mengemudi di antaranya melintasi area berskor kerawanan sedang/tinggi pada jam
perjalanan (skor dari tabel `risk_scores` milik Risk Prediction Agent).

Alur kerja = graf LangGraph (SRS: orkestrasi agent yang terstruktur & dapat
ditelusuri), tiap simpul satu langkah:

    resolve_points -> find_route -> assess_risk -> [advise] -> selesai

- resolve_points : teks lokasi -> koordinat (Mapbox Geocoding, dibatasi DIY) atau
                   koordinat langsung (mis. dari GPS); harus di dalam DIY.
- find_route     : geometri rute dari Mapbox Directions (bukan navigasi
                   turn-by-turn — di luar cakupan SRS).
- assess_risk    : PENILAIAN DETERMINISTIK (tanpa LLM): rute dijarangkan jadi titik
                   cek tiap ~250 m, tiap titik dipetakan ke sel grid & bucket jam
                   PADA SAAT titik itu dilalui (waktu berangkat + fraksi durasi),
                   lalu dicocokkan dengan skor tersimpan.
- advise         : narasi Gemini (opsional, hanya waspada/berisiko tinggi).

Aturan status (REQ-F-031) berbasis PAPARAN, deterministik, memakai `risk_level` AKHIR tiap
sel (skor dasar x pengali musim pada tanggal berangkat) — bukan angka baru. Yang dihitung
adalah jumlah (sel, bucket jam) yang dilintasi rute:

- berisiko_tinggi : sel "tinggi" >= `route_min_high_cells` (default 1), ATAU ada sel dengan
                    skor >= `route_critical_score_threshold` (default 8.5).
- waspada         : (bukan berisiko_tinggi, dan) sel "sedang" >= `route_min_medium_cells`
                    (default 2), ATAU ada sel "tinggi" walau jumlahnya di bawah syarat di atas.
- aman            : selain itu.

    sel tinggi | sel sedang | skor maks | status (default)        | catatan
    -----------+------------+-----------+-------------------------+------------------------------
        1+     |    any     |   >= 7.0  | berisiko_tinggi         | TC-RTE-001
        0      |    0       |   < 3.0   | aman                    | (lihat data_limited bila 0 data)
        0      |    1       | 3.0-6.99  | aman                    | sel sedang tetap di areas_to_watch
        0      |    2+      | 3.0-6.99  | waspada                 |
      1, min_high=2 | any   | 7.0-8.49  | waspada                 | satu sel tinggi di bawah syarat
      1, min_high=2 | any   |  >= 8.5   | berisiko_tinggi         | skor kritis menembus syarat

Kenapa konsisten dengan TC-RTE-001 ("rute yang melintasi area berskor TINGGI tidak pernah
ditampilkan sebagai aman"): sel tinggi apa pun minimal menghasilkan "waspada" untuk nilai
konfigurasi mana pun, dan "berisiko_tinggi" pada default. Satu sel "sedang" tunggal sengaja
tidak cukup untuk "waspada" (rute kota hampir selalu menyentuh satu sel sedang); areanya tetap
dicatat di `areas_to_watch`. Area yang disarankan dihindari (REQ-F-032) = sel "tinggi" yang dilintasi.

Cakupan data: `areas_with_data` / `areas_checked` dikembalikan sebagai `data_coverage` (0..1);
`data_limited` = true bila cakupan <= `route_limited_coverage_threshold` (default 0.0 = tidak ada
data sama sekali). Status "aman" pada rute tanpa data hanya berarti "belum ada data", BUKAN
jaminan aman, dan respons menyertakan keterangannya.

Rute alternatif (SRS 2.2): Mapbox diminta `alternatives=true` (maks `route_max_alternatives`
alternatif, SATU panggilan yang sama), tiap rute dinilai dengan fungsi penilaian yang sama, dan
alternatif hanya ditandai paling rendah risikonya bila levelnya lebih rendah, atau levelnya sama dan
skor tertingginya lebih rendah >= `route_alternative_min_score_gain`. Alternatif tanpa satu pun data
tidak pernah disarankan (tidak diketahui aman). Tidak ada panggilan Gemini tambahan.

KNOWN LIMITATIONS:
- "aman" berarti tidak ada paparan sel sedang/tinggi yang memenuhi syarat di atas TERCATAT di
  rute — bukan jaminan. Sel tanpa data (belum ada insiden) dianggap netral; `data_coverage`
  mengungkap seberapa luas datanya. Cakupan data antar rute alternatif tidak dinormalisasi:
  UI sebaiknya menampilkan `data_coverage` tiap alternatif.
- Titik cek tiap ~250 m: irisan rute yang lebih pendek dari itu di pojok sel
  grid bisa terlewat. Rute sangat panjang dijarangkan (`route_max_samples`).
- Perkiraan waktu tiap titik = waktu berangkat + fraksi jarak x durasi Mapbox
  (tanpa lalu lintas nyata). Pengali musim memakai tanggal berangkat.
- Geocoding nama tempat di Indonesia kasar: titik yang jatuh dekat pusat kota/kabupaten
  diberi catatan (`location_notes`), tetapi sistem tidak bisa memastikan lokasi yang dimaksud.
"""

import logging
import math
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from supabase import Client

from app.agents.risk_agent import apply_seasonality, locate_area, ramadan_phase, time_bucket_of, to_wib
from app.agents.route_narrator import RouteNarrativeFacts, generate_route_narrative
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.directions import RouteGeometry, RouteServiceUnavailable, fetch_route
from app.core.geocoding import DIY_GENERIC_CENTERS, YOGYAKARTA_BBOX, describe_area, geocode_location

logger = logging.getLogger(__name__)

ROUTE_AMAN = "aman"
ROUTE_WASPADA = "waspada"
ROUTE_BERISIKO_TINGGI = "berisiko_tinggi"

_EARTH_RADIUS_METERS = 6_371_000.0
_AREA_QUERY_CHUNK_SIZE = 40  # batas jumlah area per query supaya URL PostgREST tidak terlalu panjang
_MAX_FLAGGED_AREAS = 5  # daftar area di respons; status tetap dihitung dari SEMUA sel
_MAX_NAME_LOOKUP_WORKERS = 5
_FLAGGED_LEVEL_RANK = {"tinggi": 2, "sedang": 1}
_UNNAMED_AREA = "area tanpa nama"


class RoutePointError(Exception):
    """Titik asal/tujuan tidak bisa dipakai; pesan Indonesia aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class PlaceQuery:
    """Satu titik input: koordinat (mis. dari GPS) ATAU teks lokasi. Koordinat menang bila keduanya ada."""

    text: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class RouteSample:
    latitude: float
    longitude: float
    fraction: float  # posisi di sepanjang rute, 0.0 (asal) sampai 1.0 (tujuan)


@dataclass(frozen=True)
class CrossedCell:
    """Sebuah (sel grid, bucket jam) yang dilintasi rute, pertama kali di `position`."""

    area_name: str
    center_latitude: float
    center_longitude: float
    time_bucket: str
    position: float


@dataclass(frozen=True)
class StoredScore:
    risk_score: float
    risk_level: str


@dataclass(frozen=True)
class FlaggedArea:
    """Area sedang/tinggi yang dilintasi. Koordinat = pusat sel grid publik (bukan titik pengguna)."""

    area_name: str
    latitude: float
    longitude: float
    time_bucket: str
    risk_score: float
    risk_level: str  # "sedang" | "tinggi"
    place_name: str | None = None  # nama tingkat kecamatan, best-effort


@dataclass(frozen=True)
class RouteAssessment:
    level: str
    max_risk_score: float
    flagged_areas: tuple[FlaggedArea, ...]
    areas_checked: int  # jumlah (sel, bucket) yang dilintasi
    areas_with_data: int  # di antaranya yang punya skor tersimpan


@dataclass(frozen=True)
class AlternativeRoute:
    """Ringkasan satu rute alternatif (tanpa daftar area/nama — hanya angka agregat)."""

    assessment: RouteAssessment
    distance_km: float
    duration_minutes: int
    is_lowest_risk: bool = False  # lebih rendah risikonya dari rute utama DAN dari alternatif lain


@dataclass(frozen=True)
class DataCoverage:
    """Cakupan data skor pada rute (S1)."""

    coverage: float  # areas_with_data / areas_checked, 0..1
    limited: bool
    note: str | None


@dataclass(frozen=True)
class RouteCheckResult:
    assessment: RouteAssessment
    origin: tuple[float, float]
    destination: tuple[float, float]
    distance_km: float
    duration_minutes: int
    departure_time: datetime
    time_buckets: tuple[str, ...]
    narrative: str | None = None
    origin_name: str | None = None  # nama tempat titik asal dipetakan; selalu terisi bila pemeriksaan berhasil
    destination_name: str | None = None
    alternatives: tuple[AlternativeRoute, ...] = ()
    location_notes: tuple[str, ...] = ()  # catatan bila hasil geocoding titik diragukan


@dataclass
class RouteAgentDeps:
    """Ketergantungan eksternal agen; bisa diganti (tanpa jaringan) di test."""

    supabase: Client
    geocode: Callable[[str], tuple[float, float] | None] = geocode_location
    fetch_route: Callable[[tuple[float, float], tuple[float, float]], RouteGeometry] = fetch_route
    describe_area: Callable[[float, float], str | None] = describe_area
    narrate: Callable[[RouteNarrativeFacts], str | None] = generate_route_narrative
    settings_factory: Callable[[], Settings] = field(default=get_settings)


# ---------------------------------------------------------------- fungsi murni


def haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Jarak lingkaran-besar (meter) antara dua titik (lintang, bujur)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    half_chord = (
        math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(half_chord)))


def sample_route(
    points: tuple[tuple[float, float], ...], step_meters: float, max_samples: int
) -> list[RouteSample]:
    """Jarangkan geometri rute jadi titik cek tiap `step_meters` (selalu termasuk
    titik awal & akhir). Rute yang terlalu panjang dijarangkan supaya jumlah titik
    tidak melebihi ~`max_samples`."""
    if not points:
        raise ValueError("Geometri rute kosong")

    cumulative = [0.0]
    for previous, current in zip(points, points[1:]):
        cumulative.append(cumulative[-1] + haversine_meters(previous, current))
    total = cumulative[-1]
    if total <= 0:
        return [RouteSample(points[0][0], points[0][1], 0.0)]

    step = max(step_meters, total / max(1, max_samples - 1))
    targets = [index * step for index in range(int(total // step) + 1)]
    if total - targets[-1] > 1e-6:
        targets.append(total)

    samples: list[RouteSample] = []
    segment = 1
    for target in targets:
        while segment < len(cumulative) - 1 and cumulative[segment] < target:
            segment += 1
        span = cumulative[segment] - cumulative[segment - 1]
        ratio = 0.0 if span <= 0 else min(1.0, max(0.0, (target - cumulative[segment - 1]) / span))
        (lat0, lon0), (lat1, lon1) = points[segment - 1], points[segment]
        samples.append(RouteSample(lat0 + (lat1 - lat0) * ratio, lon0 + (lon1 - lon0) * ratio, target / total))
    return samples


def crossed_cells(
    samples: list[RouteSample], departure: datetime, duration_s: float, settings: Settings
) -> list[CrossedCell]:
    """(Sel grid, bucket jam) unik yang dilintasi, urut sesuai kedatangan pertama.

    Bucket dihitung dari waktu TIBA di tiap titik (berangkat + fraksi x durasi),
    jadi rute yang melewati pergantian jam (mis. berangkat 17.50) dinilai dengan
    skor jam yang sesuai di tiap bagiannya.
    """
    seen: dict[tuple[str, str], CrossedCell] = {}
    for sample in samples:
        arrival = departure + timedelta(seconds=duration_s * sample.fraction)
        bucket = time_bucket_of(arrival)
        center_lat, center_lon, area_name = locate_area(sample.latitude, sample.longitude, settings.risk_grid_cell_degrees)
        seen.setdefault((area_name, bucket), CrossedCell(area_name, center_lat, center_lon, bucket, sample.fraction))
    return list(seen.values())


def assess_route(
    cells: list[CrossedCell], scores: dict[tuple[str, str], StoredScore], settings: Settings | None = None
) -> RouteAssessment:
    """Status rute dari paparan sel sedang/tinggi yang dilintasi (REQ-F-030/031/032).

    Aturan & tabel contoh: lihat docstring modul. Dihitung dari SEMUA sel (daftar area di
    respons hanya dipotong untuk tampilan)."""
    settings = settings or get_settings()
    flagged: list[FlaggedArea] = []
    areas_with_data = 0
    max_score = 0.0
    for cell in cells:
        stored = scores.get((cell.area_name, cell.time_bucket))
        if stored is None:
            continue  # belum ada data untuk sel/jam ini: netral, bukan "aman" (lihat KNOWN LIMITATIONS)
        areas_with_data += 1
        max_score = max(max_score, stored.risk_score)
        if stored.risk_level in _FLAGGED_LEVEL_RANK:
            flagged.append(
                FlaggedArea(
                    area_name=cell.area_name,
                    latitude=cell.center_latitude,
                    longitude=cell.center_longitude,
                    time_bucket=cell.time_bucket,
                    risk_score=stored.risk_score,
                    risk_level=stored.risk_level,
                )
            )

    high_cells = sum(1 for area in flagged if area.risk_level == "tinggi")
    medium_cells = len(flagged) - high_cells
    if high_cells >= settings.route_min_high_cells or max_score >= settings.route_critical_score_threshold:
        level = ROUTE_BERISIKO_TINGGI
    elif high_cells >= 1 or medium_cells >= settings.route_min_medium_cells:
        level = ROUTE_WASPADA
    else:
        level = ROUTE_AMAN

    flagged.sort(key=lambda area: (_FLAGGED_LEVEL_RANK[area.risk_level], area.risk_score), reverse=True)
    return RouteAssessment(
        level=level,
        max_risk_score=max_score,
        flagged_areas=tuple(flagged[:_MAX_FLAGGED_AREAS]),
        areas_checked=len(cells),
        areas_with_data=areas_with_data,
    )


def describe_data_coverage(assessment: RouteAssessment, settings: Settings | None = None) -> DataCoverage:
    """Cakupan data rute (S1). `limited` bila cakupan <= `route_limited_coverage_threshold`
    (default 0.0 = tidak ada data sama sekali); status tetap apa adanya (kompatibel dengan SRS),
    yang ditambahkan hanya keterangan bahwa itu bukan jaminan aman."""
    settings = settings or get_settings()
    checked, with_data = assessment.areas_checked, assessment.areas_with_data
    coverage = round(with_data / checked, 3) if checked else 0.0
    limited = checked == 0 or coverage <= settings.route_limited_coverage_threshold
    note = None
    if limited:
        note = (
            "Belum ada data kerawanan pada rute ini, bukan jaminan aman."
            if with_data == 0
            else f"Data kerawanan hanya tersedia untuk {with_data} dari {checked} area yang dilintasi; "
            "hasil terbatas pada data tersebut dan bukan jaminan aman."
        )
    return DataCoverage(coverage=coverage, limited=limited, note=note)


_LEVEL_RANK = {ROUTE_AMAN: 0, ROUTE_WASPADA: 1, ROUTE_BERISIKO_TINGGI: 2}


def _is_clearly_lower_risk(candidate: RouteAssessment, reference: RouteAssessment, min_score_gain: float) -> bool:
    """Level lebih rendah, atau level sama dengan skor tertinggi lebih rendah >= `min_score_gain`."""
    if _LEVEL_RANK[candidate.level] != _LEVEL_RANK[reference.level]:
        return _LEVEL_RANK[candidate.level] < _LEVEL_RANK[reference.level]
    return candidate.max_risk_score <= reference.max_risk_score - min_score_gain


def build_alternatives(
    main: RouteAssessment,
    alternatives: Sequence[tuple[RouteAssessment, float, int]],
    settings: Settings | None = None,
) -> tuple[AlternativeRoute, ...]:
    """Ringkasan alternatif (urutan Mapbox) dan penanda yang paling rendah risikonya.

    `alternatives` = (penilaian, jarak km, durasi menit). Penanda `is_lowest_risk` hanya jatuh pada
    SATU alternatif: yang jelas lebih rendah risikonya dari rute utama (lihat
    `_is_clearly_lower_risk`) dan terbaik di antara alternatif (level, skor, lalu durasi tercepat).
    Alternatif tanpa data sama sekali tidak pernah ditandai: tidak diketahui aman."""
    settings = settings or get_settings()
    qualified = [
        index
        for index, (assessment, _, _) in enumerate(alternatives)
        if assessment.areas_with_data > 0
        and _is_clearly_lower_risk(assessment, main, settings.route_alternative_min_score_gain)
    ]
    best = min(
        qualified,
        key=lambda i: (_LEVEL_RANK[alternatives[i][0].level], alternatives[i][0].max_risk_score, alternatives[i][2]),
        default=None,
    )
    return tuple(
        AlternativeRoute(assessment, distance_km, duration_minutes, is_lowest_risk=index == best)
        for index, (assessment, distance_km, duration_minutes) in enumerate(alternatives)
    )


def generic_center_name(point: tuple[float, float], radius_meters: float) -> str | None:
    """Nama kota/kabupaten DIY bila `point` jatuh dalam `radius_meters` dari titik pusatnya
    (tanda geocoding mengembalikan pusat wilayah, bukan lokasi spesifik), selain itu None."""
    name, distance = min(
        ((name, haversine_meters(point, center)) for name, center in DIY_GENERIC_CENTERS.items()),
        key=lambda item: item[1],
    )
    return name if distance <= radius_meters else None


def _in_yogyakarta(point: tuple[float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    return min_lat <= point[0] <= max_lat and min_lon <= point[1] <= max_lon


def _unique_in_order(names: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def build_narrative_facts(
    assessment: RouteAssessment,
    cells: list[CrossedCell],
    distance_km: float,
    duration_minutes: int,
    season: str | None = None,
) -> RouteNarrativeFacts:
    """Fakta agregat untuk narasi: nama area (bukan koordinat), jam, jarak, cakupan data."""

    def names(level: str) -> tuple[str, ...]:
        return _unique_in_order([a.place_name or _UNNAMED_AREA for a in assessment.flagged_areas if a.risk_level == level])

    return RouteNarrativeFacts(
        route_level=assessment.level,
        max_risk_score=round(assessment.max_risk_score, 1),
        time_buckets=_unique_in_order([cell.time_bucket for cell in cells]),
        avoid_places=names("tinggi"),
        watch_places=names("sedang"),
        distance_km=round(distance_km, 1),
        duration_minutes=duration_minutes,
        areas_checked=assessment.areas_checked,
        areas_with_data=assessment.areas_with_data,
        season=season,
    )


# ---------------------------------------------------------------------- database


def fetch_route_scores(
    supabase: Client, cells: list[CrossedCell], on_date: date, settings: Settings | None = None
) -> dict[tuple[str, str], StoredScore]:
    """Skor AKHIR untuk (sel, bucket) yang dilintasi — hanya baca tabel `risk_scores`
    (RLS: baca publik), difilter lewat query berparameter supabase-py (bukan SQL mentah).

    Skor dasar tersimpan dikali pengali musim pada `on_date` (tanggal berangkat), dibatasi 10,
    dan level ditentukan dari skor akhir itu (sama seperti `lookup_risk_score`)."""
    settings = settings or get_settings()
    wanted = {(cell.area_name, cell.time_bucket) for cell in cells}
    areas = sorted({area for area, _ in wanted})
    buckets = sorted({bucket for _, bucket in wanted})

    scores: dict[tuple[str, str], StoredScore] = {}
    for start in range(0, len(areas), _AREA_QUERY_CHUNK_SIZE):
        response = execute_with_retry(
            supabase.table("risk_scores")
            .select("area_name,time_bucket,risk_score,risk_level")
            .in_("area_name", areas[start : start + _AREA_QUERY_CHUNK_SIZE])
            .in_("time_bucket", buckets)
        )
        for row in response.data or []:
            key = (row["area_name"], row["time_bucket"])
            if key in wanted:
                seasonal = apply_seasonality(float(row["risk_score"]), on_date, row["time_bucket"], settings)
                scores[key] = StoredScore(risk_score=seasonal.score, risk_level=seasonal.level)
    return scores


def _safe_describe(describe: Callable[[float, float], str | None], latitude: float, longitude: float) -> str | None:
    """Nama area best-effort: kegagalan apa pun = tanpa nama, bukan error (hanya pemanis)."""
    try:
        return describe(latitude, longitude)
    except Exception as exc:  # noqa: BLE001 - nama area tidak boleh menggagalkan pemeriksaan rute
        logger.warning("Nama area dilewati: %s", type(exc).__name__)
        return None


def _name_flagged_areas(
    assessment: RouteAssessment, describe: Callable[[float, float], str | None]
) -> RouteAssessment:
    """Isi `place_name` (best-effort, paralel; kegagalan = tanpa nama, bukan error)."""
    areas = assessment.flagged_areas
    if not areas:
        return assessment

    with ThreadPoolExecutor(max_workers=min(_MAX_NAME_LOOKUP_WORKERS, len(areas))) as pool:
        names = list(pool.map(lambda area: _safe_describe(describe, area.latitude, area.longitude), areas))
    named = tuple(replace(area, place_name=name) for area, name in zip(areas, names, strict=True))
    return replace(assessment, flagged_areas=named)


# ------------------------------------------------------------------- graf LangGraph


class RouteCheckState(TypedDict, total=False):
    origin_query: PlaceQuery
    destination_query: PlaceQuery
    departure: datetime
    include_narrative: bool
    origin: tuple[float, float]
    destination: tuple[float, float]
    origin_name: str | None
    destination_name: str | None
    location_notes: list[str]
    route: RouteGeometry
    cells: list[CrossedCell]
    assessment: RouteAssessment
    alternatives: tuple[AlternativeRoute, ...]
    narrative: str | None


def _resolve_point(query: PlaceQuery, label: str, deps: RouteAgentDeps) -> tuple[float, float]:
    """Koordinat titik `label` ("asal"/"tujuan"), dijamin di dalam wilayah DIY."""
    if query.latitude is not None and query.longitude is not None:
        point = (query.latitude, query.longitude)
        if not _in_yogyakarta(point):
            raise RoutePointError(f"Titik {label} berada di luar wilayah Yogyakarta.")
        return point

    if not query.text:
        raise RoutePointError(f"Titik {label} belum diisi.")
    if not deps.settings_factory().mapbox_token:
        raise RouteServiceUnavailable("MAPBOX_TOKEN belum diset")
    point = deps.geocode(query.text)
    if point is None:
        raise RoutePointError(
            f'Lokasi {label} tidak ditemukan di wilayah Yogyakarta. Coba sertakan nama kecamatan atau "Yogyakarta".'
        )
    return point


def _fallback_place_name(query: PlaceQuery, point: tuple[float, float], settings: Settings) -> str:
    """Nama titik bila reverse geocoding gagal/tanpa token: teks yang diketik pengguna sendiri
    (hanya dikembalikan ke pengguna yang sama, tidak dicatat/disimpan/dikirim ke Gemini), atau
    label sel grid yang netral untuk titik koordinat/GPS."""
    if query.latitude is None and query.longitude is None and query.text:
        return query.text
    return locate_area(point[0], point[1], settings.risk_grid_cell_degrees)[2]


def _location_note(query: PlaceQuery, point: tuple[float, float], label: str, settings: Settings) -> str | None:
    """Catatan bila titik dari TEKS jatuh di pusat kota/kabupaten (geocoding diragukan).
    Titik dari koordinat/GPS tidak pernah diberi catatan ini."""
    if query.latitude is not None and query.longitude is not None:
        return None
    center = generic_center_name(point, settings.route_geocode_generic_radius_meters)
    if center is None:
        return None
    return (
        f"Titik {label} dipetakan ke sekitar pusat {center}, bisa jadi bukan lokasi yang Anda maksud "
        "(nama tempat yang tidak dikenali sering jatuh ke pusat wilayah). Periksa nama area pada hasil, "
        "tambahkan nama jalan atau kecamatan, atau gunakan lokasi GPS."
    )


def build_route_graph(deps: RouteAgentDeps):
    """Susun & kompilasi graf pemeriksaan rute. Exception domain (RoutePointError,
    RouteNotFound, RouteServiceUnavailable) dibiarkan naik ke pemanggil (API)."""
    settings = deps.settings_factory()

    def resolve_points(state: RouteCheckState) -> RouteCheckState:
        origin_query, destination_query = state["origin_query"], state["destination_query"]
        origin = _resolve_point(origin_query, "asal", deps)
        destination = _resolve_point(destination_query, "tujuan", deps)
        # Nama area tempat titik dipetakan: geocoding nama tempat di Indonesia kasar
        # (banyak nama jatuh ke pusat kota), jadi pengguna perlu melihat titik mana
        # yang sebenarnya dipakai. Best-effort, paralel; nama SELALU terisi lewat fallback.
        with ThreadPoolExecutor(max_workers=2) as pool:
            origin_name, destination_name = pool.map(
                lambda point: _safe_describe(deps.describe_area, *point), (origin, destination)
            )
        notes = [
            note
            for note in (
                _location_note(origin_query, origin, "asal", settings),
                _location_note(destination_query, destination, "tujuan", settings),
            )
            if note
        ]
        return {
            "origin": origin,
            "destination": destination,
            "origin_name": origin_name or _fallback_place_name(origin_query, origin, settings),
            "destination_name": destination_name or _fallback_place_name(destination_query, destination, settings),
            "location_notes": notes,
        }

    def find_route(state: RouteCheckState) -> RouteCheckState:
        return {"route": deps.fetch_route(state["origin"], state["destination"])}

    def assess_risk(state: RouteCheckState) -> RouteCheckState:
        route = state["route"]
        alternatives = route.alternatives[: max(0, settings.route_max_alternatives)]
        all_routes = [route, *alternatives]

        # Semua rute dinilai dengan fungsi yang sama; skor sel dibaca SEKALI untuk gabungan sel.
        samples_per_route = [
            sample_route(r.points, settings.route_sample_step_meters, settings.route_max_samples) for r in all_routes
        ]
        cells_per_route = [
            crossed_cells(samples, state["departure"], r.duration_s, settings)
            for samples, r in zip(samples_per_route, all_routes, strict=True)
        ]
        scores = fetch_route_scores(
            deps.supabase,
            [cell for cells in cells_per_route for cell in cells],
            to_wib(state["departure"]).date(),
            settings,
        )
        assessments = [assess_route(cells, scores, settings) for cells in cells_per_route]

        cells = cells_per_route[0]
        assessment = _name_flagged_areas(assessments[0], deps.describe_area)  # hanya rute utama yang diberi nama
        summaries = build_alternatives(
            assessment,
            [
                (alt_assessment, round(alt.distance_m / 1000, 1), round(alt.duration_s / 60))
                for alt, alt_assessment in zip(alternatives, assessments[1:], strict=True)
            ],
            settings,
        )
        # Log hanya hitungan & status — tanpa teks lokasi/koordinat pengguna.
        logger.info(
            "Cek rute: %d titik cek, %d area dilintasi (%d berdata), status=%s, %d alternatif",
            len(samples_per_route[0]),
            assessment.areas_checked,
            assessment.areas_with_data,
            assessment.level,
            len(summaries),
        )
        return {"cells": cells, "assessment": assessment, "alternatives": summaries}

    def advise(state: RouteCheckState) -> RouteCheckState:
        route = state["route"]
        facts = build_narrative_facts(
            state["assessment"],
            state["cells"],
            route.distance_m / 1000,
            round(route.duration_s / 60),
            season=ramadan_phase(to_wib(state["departure"]).date(), settings),
        )
        return {"narrative": deps.narrate(facts)}

    def needs_advice(state: RouteCheckState) -> str:
        wants_narrative = state.get("include_narrative") and state["assessment"].level != ROUTE_AMAN
        return "advise" if wants_narrative else END

    graph = StateGraph(RouteCheckState)
    graph.add_node("resolve_points", resolve_points)
    graph.add_node("find_route", find_route)
    graph.add_node("assess_risk", assess_risk)
    graph.add_node("advise", advise)
    graph.add_edge(START, "resolve_points")
    graph.add_edge("resolve_points", "find_route")
    graph.add_edge("find_route", "assess_risk")
    graph.add_conditional_edges("assess_risk", needs_advice, {"advise": "advise", END: END})
    graph.add_edge("advise", END)
    return graph.compile()


def run_route_check(
    deps: RouteAgentDeps,
    origin: PlaceQuery,
    destination: PlaceQuery,
    departure: datetime,
    include_narrative: bool = False,
) -> RouteCheckResult:
    """Jalankan pemeriksaan rute penuh. `departure` harus timezone-aware.

    Melempar RoutePointError (titik tidak valid), RouteNotFound / RouteServiceUnavailable
    (layanan rute), atau error database dari pembacaan skor; API yang memetakannya ke HTTP.
    """
    final_state = build_route_graph(deps).invoke(
        {
            "origin_query": origin,
            "destination_query": destination,
            "departure": departure,
            "include_narrative": include_narrative,
        }
    )
    route = final_state["route"]
    return RouteCheckResult(
        assessment=final_state["assessment"],
        origin=final_state["origin"],
        destination=final_state["destination"],
        distance_km=round(route.distance_m / 1000, 1),
        duration_minutes=round(route.duration_s / 60),
        departure_time=departure,
        time_buckets=_unique_in_order([cell.time_bucket for cell in final_state["cells"]]),
        narrative=final_state.get("narrative"),
        origin_name=final_state.get("origin_name"),
        destination_name=final_state.get("destination_name"),
        alternatives=final_state.get("alternatives", ()),
        location_notes=tuple(final_state.get("location_notes", ())),
    )
