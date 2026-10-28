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

Aturan status (REQ-F-031) memakai `risk_level` tersimpan tiap sel — bukan angka
baru: ada sel "tinggi" -> berisiko_tinggi; kalau tidak, ada sel "sedang" ->
waspada; selain itu aman. Satu sel tinggi saja cukup (TC-RTE-001: rute yang
melintasi area berskor tinggi TIDAK PERNAH ditampilkan sebagai aman).
Area yang disarankan dihindari (REQ-F-032) = sel "tinggi" yang dilintasi.

KNOWN LIMITATIONS:
- "aman" berarti tidak ada sel sedang/tinggi TERCATAT di rute — bukan jaminan.
  Sel tanpa data (belum ada insiden) dianggap netral; `areas_with_data` vs
  `areas_checked` dikembalikan supaya cakupan datanya transparan.
- Titik cek tiap ~250 m: irisan rute yang lebih pendek dari itu di pojok sel
  grid bisa terlewat. Rute sangat panjang dijarangkan (`route_max_samples`).
- Perkiraan waktu tiap titik = waktu berangkat + fraksi jarak x durasi Mapbox
  (tanpa lalu lintas nyata).
- Hanya rute utama Mapbox; belum ada perbandingan rute alternatif.
"""

import logging
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from supabase import Client

from app.agents.risk_agent import locate_area, time_bucket_of
from app.agents.route_narrator import RouteNarrativeFacts, generate_route_narrative
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.directions import RouteGeometry, RouteServiceUnavailable, fetch_route
from app.core.geocoding import YOGYAKARTA_BBOX, describe_area, geocode_location

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
class RouteCheckResult:
    assessment: RouteAssessment
    origin: tuple[float, float]
    destination: tuple[float, float]
    distance_km: float
    duration_minutes: int
    departure_time: datetime
    time_buckets: tuple[str, ...]
    narrative: str | None = None
    origin_name: str | None = None  # nama area (kecamatan/desa) tempat titik asal dipetakan
    destination_name: str | None = None


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


def assess_route(cells: list[CrossedCell], scores: dict[tuple[str, str], StoredScore]) -> RouteAssessment:
    """Status rute dari `risk_level` tersimpan tiap sel yang dilintasi (REQ-F-030/031/032)."""
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

    if any(area.risk_level == "tinggi" for area in flagged):
        level = ROUTE_BERISIKO_TINGGI
    elif flagged:
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


def _in_yogyakarta(point: tuple[float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    return min_lat <= point[0] <= max_lat and min_lon <= point[1] <= max_lon


def _unique_in_order(names: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def build_narrative_facts(
    assessment: RouteAssessment, cells: list[CrossedCell], distance_km: float, duration_minutes: int
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
    )


# ---------------------------------------------------------------------- database


def fetch_route_scores(supabase: Client, cells: list[CrossedCell]) -> dict[tuple[str, str], StoredScore]:
    """Skor tersimpan untuk (sel, bucket) yang dilintasi — hanya baca tabel `risk_scores`
    (RLS: baca publik), difilter lewat query berparameter supabase-py (bukan SQL mentah)."""
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
                scores[key] = StoredScore(risk_score=float(row["risk_score"]), risk_level=row["risk_level"])
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
    route: RouteGeometry
    cells: list[CrossedCell]
    assessment: RouteAssessment
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


def build_route_graph(deps: RouteAgentDeps):
    """Susun & kompilasi graf pemeriksaan rute. Exception domain (RoutePointError,
    RouteNotFound, RouteServiceUnavailable) dibiarkan naik ke pemanggil (API)."""
    settings = deps.settings_factory()

    def resolve_points(state: RouteCheckState) -> RouteCheckState:
        origin = _resolve_point(state["origin_query"], "asal", deps)
        destination = _resolve_point(state["destination_query"], "tujuan", deps)
        # Nama area tempat titik dipetakan: geocoding nama tempat di Indonesia kasar
        # (banyak nama jatuh ke pusat kota), jadi pengguna perlu melihat titik mana
        # yang sebenarnya dipakai. Best-effort, paralel.
        with ThreadPoolExecutor(max_workers=2) as pool:
            origin_name, destination_name = pool.map(
                lambda point: _safe_describe(deps.describe_area, *point), (origin, destination)
            )
        return {
            "origin": origin,
            "destination": destination,
            "origin_name": origin_name,
            "destination_name": destination_name,
        }

    def find_route(state: RouteCheckState) -> RouteCheckState:
        return {"route": deps.fetch_route(state["origin"], state["destination"])}

    def assess_risk(state: RouteCheckState) -> RouteCheckState:
        route = state["route"]
        samples = sample_route(route.points, settings.route_sample_step_meters, settings.route_max_samples)
        cells = crossed_cells(samples, state["departure"], route.duration_s, settings)
        assessment = _name_flagged_areas(assess_route(cells, fetch_route_scores(deps.supabase, cells)), deps.describe_area)
        # Log hanya hitungan & status — tanpa teks lokasi/koordinat pengguna.
        logger.info(
            "Cek rute: %d titik cek, %d area dilintasi (%d berdata), status=%s",
            len(samples),
            assessment.areas_checked,
            assessment.areas_with_data,
            assessment.level,
        )
        return {"cells": cells, "assessment": assessment}

    def advise(state: RouteCheckState) -> RouteCheckState:
        route = state["route"]
        facts = build_narrative_facts(
            state["assessment"], state["cells"], route.distance_m / 1000, round(route.duration_s / 60)
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
    )
