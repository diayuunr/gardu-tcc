"""Safe Route Advisor (REQ-F-030, REQ-F-031, REQ-F-032).

Menerima titik asal, tujuan, dan waktu berangkat, lalu menelusuri jalan-jalan yang dilalui rute mengemudi
dan memeriksa riwayat kejadian terskor di sekitar jalur itu pada jam perjalanan.

Alur kerja = graf LangGraph (SRS: orkestrasi agent yang terstruktur & dapat ditelusuri), tiap simpul satu langkah:

    resolve_points -> find_route -> assess_risk -> [advise] -> selesai

- resolve_points : teks lokasi -> koordinat (Mapbox Geocoding, dibatasi DIY; asal & tujuan PARALEL) atau
                   koordinat langsung (mis. GPS); harus di dalam DIY. Catatan bila hasil geocoding diragukan.
- find_route     : rute utama + alternatif (maks 2) dari SATU panggilan Mapbox Directions dengan nama jalan per
                   langkah (steps). Indeks insiden dimuat PARALEL dengan panggilan itu (dari cache bila segar).
- assess_risk    : PENILAIAN DETERMINISTIK tanpa LLM (aturan, bobot, dan tabel contoh status: lihat docstring
                   app/agents/route_analysis.py): titik cek tiap ~125 m, insiden dalam radius 300 m dibobot
                   jarak x kebaruan x kesesuaian jam TIBA di titik itu x pengali musim, dikelompokkan per nama
                   jalan, lalu status aman/waspada/berisiko_tinggi beserta alasan (`reasons`). Nama kecamatan
                   tiap ruas dari tabel areas (kecamatan terdekat) — tanpa panggilan jaringan.
- advise         : narasi Gemini (opsional, hanya waspada/berisiko tinggi) yang hanya MENJELASKAN hasil di atas.

Performa: satu pemeriksaan = 1 geocoding per titik teks (paralel) + 1 Directions + pembacaan indeks insiden
(cache) + komputasi di memori; tidak ada query database per titik maupun per area.

KNOWN LIMITATIONS: lihat docstring app/agents/route_analysis.py. Tambahan: geocoding nama tempat di Indonesia
kasar — titik yang jatuh dekat pusat kota/kabupaten diberi catatan (`location_notes`), tetapi sistem tidak bisa
memastikan lokasi yang dimaksud.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from supabase import Client

from app.agents.incident_index import IncidentIndex, get_incident_index
from app.agents.risk_agent import locate_area, ramadan_phase, to_wib
from app.agents.route_analysis import (  # noqa: F401 - sebagian diekspor ulang untuk pemanggil lain
    LEVEL_RANK,
    ROUTE_AMAN,
    ROUTE_BERISIKO_TINGGI,
    ROUTE_WASPADA,
    RouteAnalysis,
    RouteSample,
    analyze_route,
    build_reasons,
    is_data_limited,
    pick_safer_alternative,
    sample_route,
)
from app.agents.route_narrator import RouteNarrativeFacts, generate_route_narrative
from app.core.areas import AreaDirectory, get_directory_or_none
from app.core.config import Settings, get_settings
from app.core.directions import RouteGeometry, RouteServiceUnavailable, fetch_route
from app.core.geo import haversine_meters
from app.core.geocoding import DIY_GENERIC_CENTERS, YOGYAKARTA_BBOX, describe_area
from app.core.places import resolve_place

logger = logging.getLogger(__name__)

_MAX_FLAGGED_AREAS = 5  # daftar area di respons; status tetap dihitung dari SEMUA titik
_FLAGGED_LEVEL_RANK = {"tinggi": 2, "sedang": 1}


class RoutePointError(Exception):
    """Titik asal/tujuan tidak bisa dipakai; pesan Indonesia aman ditampilkan ke pengguna."""


@dataclass(frozen=True)
class PlaceQuery:
    """Satu titik input: koordinat (mis. dari GPS) ATAU teks lokasi. Koordinat menang bila keduanya ada."""

    text: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class FlaggedArea:
    """Ruas jalan berlevel sedang/tinggi. Koordinat = TITIK TENGAH ruas di jalur (bukan lokasi insiden, bukan
    titik puncak skor), `area_name` = nama jalan, `place_name` = "Kec. X"."""

    area_name: str
    latitude: float
    longitude: float
    time_bucket: str
    risk_score: float
    risk_level: str  # "sedang" | "tinggi"
    place_name: str | None = None
    segment_index: int | None = None


@dataclass(frozen=True)
class RouteAssessment:
    level: str
    max_risk_score: float
    flagged_areas: tuple[FlaggedArea, ...]
    areas_checked: int  # jumlah titik cek
    areas_with_data: int  # di antaranya yang punya insiden terskor di sekitarnya (cakupan data)
    high_exposure_m: float = 0.0
    medium_exposure_m: float = 0.0
    incident_count: int = 0  # insiden berbeda yang berkontribusi (agregat; tanpa identitas/koordinat)


@dataclass(frozen=True)
class DataCoverage:
    """Cakupan data pada rute (S1)."""

    coverage: float  # titik berdata / titik cek, 0..1
    limited: bool
    note: str | None


@dataclass(frozen=True)
class AlternativeRoute:
    """Rute alternatif Mapbox beserta penilaiannya (analisis penuh: segmen, geometri, alasan)."""

    assessment: RouteAssessment
    analysis: RouteAnalysis | None
    distance_km: float
    duration_minutes: int
    extra_minutes: int = 0  # selisih waktu tempuh terhadap rute utama (negatif = lebih cepat)
    is_lowest_risk: bool = False  # jelas lebih rendah risikonya dari rute utama DAN dari alternatif lain


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
    analysis: RouteAnalysis | None = None  # analisis rute utama (segmen, geometri, alasan)


@dataclass
class RouteAgentDeps:
    """Ketergantungan eksternal agen; bisa diganti (tanpa jaringan) di test."""

    supabase: Client
    # Geocoding teks asal/tujuan. None = resolver berlapis yang SAMA dengan /geo/search (landmark > Photon > wilayah > Mapbox).
    geocode: Callable[[str], tuple[float, float] | None] | None = None
    fetch_route: Callable[[tuple[float, float], tuple[float, float]], RouteGeometry] = fetch_route
    describe_area: Callable[[float, float], str | None] = describe_area
    narrate: Callable[[RouteNarrativeFacts], str | None] = generate_route_narrative
    settings_factory: Callable[[], Settings] = field(default=get_settings)
    incident_loader: Callable[[Client], IncidentIndex] = get_incident_index
    directory_loader: Callable[[Client], AreaDirectory | None] = get_directory_or_none


# ---------------------------------------------------------------- fungsi murni


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
            "Belum ada data kejadian di sekitar rute ini, bukan jaminan aman."
            if with_data == 0
            else f"Data kejadian hanya tersedia di sekitar {with_data} dari {checked} titik pemeriksaan; "
            "hasil terbatas pada data tersebut dan bukan jaminan aman."
        )
    return DataCoverage(coverage=coverage, limited=limited, note=note)


def assessment_of(analysis: RouteAnalysis) -> RouteAssessment:
    """Ringkasan kompatibel (status, skor, ruas berisiko) dari analisis; ruas diurutkan skor tertinggi."""
    flagged = sorted(
        (s for s in analysis.segments if s.level in _FLAGGED_LEVEL_RANK),
        key=lambda s: (-_FLAGGED_LEVEL_RANK[s.level], -s.max_score, s.index),
    )
    return RouteAssessment(
        level=analysis.status,
        max_risk_score=analysis.max_score,
        flagged_areas=tuple(
            FlaggedArea(
                area_name=s.road_name,
                latitude=s.mid_latitude,
                longitude=s.mid_longitude,
                time_bucket=s.peak_bucket,
                risk_score=s.max_score,
                risk_level=s.level,
                place_name=s.place_name,
                segment_index=s.index,
            )
            for s in flagged[:_MAX_FLAGGED_AREAS]
        ),
        areas_checked=analysis.checked_points,
        areas_with_data=analysis.covered_points,
        high_exposure_m=analysis.high_exposure_m,
        medium_exposure_m=analysis.medium_exposure_m,
        incident_count=analysis.incident_count,
    )


def name_segments(analysis: RouteAnalysis, directory: AreaDirectory | None, settings: Settings) -> RouteAnalysis:
    """Isi `place_name` tiap ruas dengan kecamatan terdekat (memori saja, tanpa jaringan). Ruas berskor dinamai
    dari titik PUNCAKNYA (tempat yang berisiko); ruas tanpa skor dari titik tengah geometrinya, karena titik
    awalnya bisa berada di kecamatan lain dari sebagian besar ruas itu."""
    if directory is None:
        return analysis
    named = []
    for segment in analysis.segments:
        if segment.max_score > 0:
            lat, lon = segment.peak_latitude, segment.peak_longitude
        else:
            lat, lon = segment.mid_latitude, segment.mid_longitude
        kecamatan = directory.nearest_kecamatan(lat, lon, settings.risk_place_max_distance_meters)
        named.append(replace(segment, place_name=directory.place_name(kecamatan) if kecamatan else None))
    return replace(analysis, segments=tuple(named))


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


def _unique_in_order(names) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _segment_label(area: FlaggedArea) -> str:
    return f"{area.area_name} ({area.place_name})" if area.place_name else area.area_name


def build_narrative_facts(
    assessment: RouteAssessment,
    analysis: RouteAnalysis,
    distance_km: float,
    duration_minutes: int,
    season: str | None = None,
) -> RouteNarrativeFacts:
    """Fakta agregat untuk narasi: nama jalan & kecamatan (bukan koordinat), jam, jarak, cakupan data."""

    def names(level: str) -> tuple[str, ...]:
        return _unique_in_order(_segment_label(a) for a in assessment.flagged_areas if a.risk_level == level)

    return RouteNarrativeFacts(
        route_level=assessment.level,
        max_risk_score=round(assessment.max_risk_score, 1),
        time_buckets=analysis.time_buckets,
        avoid_places=names("tinggi"),
        watch_places=names("sedang"),
        distance_km=round(distance_km, 1),
        duration_minutes=duration_minutes,
        areas_checked=assessment.areas_checked,
        areas_with_data=assessment.areas_with_data,
        season=season,
    )


def _safe_describe(describe: Callable[[float, float], str | None], latitude: float, longitude: float) -> str | None:
    """Nama area best-effort: kegagalan apa pun = tanpa nama, bukan error (hanya pemanis)."""
    try:
        return describe(latitude, longitude)
    except Exception as exc:  # noqa: BLE001 - nama area tidak boleh menggagalkan pemeriksaan rute
        logger.warning("Nama area dilewati: %s", type(exc).__name__)
        return None


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
    index: IncidentIndex
    analysis: RouteAnalysis
    assessment: RouteAssessment
    alternatives: tuple[AlternativeRoute, ...]
    narrative: str | None


def _resolve_point(
    query: PlaceQuery, label: str, deps: RouteAgentDeps, directory: AreaDirectory | None = None
) -> tuple[float, float]:
    """Koordinat titik `label` ("asal"/"tujuan"), dijamin di dalam wilayah DIY. Teks diselesaikan oleh resolver
    berlapis yang sama dengan /geo/search (hasil teratas yang valid); landmark/Photon tidak butuh token Mapbox."""
    if query.latitude is not None and query.longitude is not None:
        point = (query.latitude, query.longitude)
        if not _in_yogyakarta(point):
            raise RoutePointError(f"Titik {label} berada di luar wilayah Yogyakarta.")
        return point

    if not query.text:
        raise RoutePointError(f"Titik {label} belum diisi.")
    point = deps.geocode(query.text) if deps.geocode is not None else resolve_place(query.text, directory)
    if point is None:
        raise RoutePointError(
            f'Lokasi {label} tidak ditemukan di wilayah Yogyakarta. Coba sertakan nama kecamatan atau "Yogyakarta".'
        )
    return point


def _fallback_place_name(
    query: PlaceQuery, point: tuple[float, float], settings: Settings, directory: AreaDirectory | None = None
) -> str:
    """Nama titik bila reverse geocoding gagal/tanpa token, berurutan: teks yang diketik pengguna sendiri
    (hanya dikembalikan ke pengguna yang sama, tidak dicatat/disimpan/dikirim ke Gemini); nama kecamatan
    terdekat dari data wilayah (memori saja); terakhir label sel grid yang netral."""
    if query.latitude is None and query.longitude is None and query.text:
        return query.text
    if directory is not None:
        kecamatan = directory.nearest_kecamatan(point[0], point[1], settings.risk_place_max_distance_meters)
        if kecamatan is not None:
            return directory.place_name(kecamatan)
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


def _minutes_phrase(extra_minutes: int) -> str:
    if extra_minutes > 0:
        return f"sekitar {extra_minutes} menit lebih lama"
    if extra_minutes < 0:
        return f"sekitar {-extra_minutes} menit lebih singkat"
    return "dengan waktu tempuh yang sama"


def build_route_graph(deps: RouteAgentDeps):
    """Susun & kompilasi graf pemeriksaan rute. Exception domain (RoutePointError,
    RouteNotFound, RouteServiceUnavailable) dibiarkan naik ke pemanggil (API)."""
    settings = deps.settings_factory()

    def resolve_points(state: RouteCheckState) -> RouteCheckState:
        origin_query, destination_query = state["origin_query"], state["destination_query"]
        directory = deps.directory_loader(deps.supabase)  # cache memori; dipakai resolver teks & nama titik
        with ThreadPoolExecutor(max_workers=2) as pool:  # dua geocoding teks berjalan bersamaan
            origin_future = pool.submit(_resolve_point, origin_query, "asal", deps, directory)
            destination_future = pool.submit(_resolve_point, destination_query, "tujuan", deps, directory)
            origin, destination = origin_future.result(), destination_future.result()
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
            "location_notes": notes,
        }

    def find_route(state: RouteCheckState) -> RouteCheckState:
        # Rute (jaringan), indeks insiden (cache/DB), dan nama kedua titik dimuat BERSAMAAN (dulu nama diambil
        # berurutan sebelum rute: +~2 dtk saat cache dingin); kegagalan Mapbox Directions didahulukan.
        # Nama area tempat titik dipetakan: geocoding nama tempat di Indonesia kasar (banyak nama jatuh ke
        # pusat kota), jadi pengguna perlu melihat titik mana yang sebenarnya dipakai. Best-effort; nama SELALU
        # terisi lewat fallback.
        origin, destination = state["origin"], state["destination"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            route_future = pool.submit(deps.fetch_route, origin, destination)
            index_future = pool.submit(deps.incident_loader, deps.supabase)
            name_futures = [pool.submit(_safe_describe, deps.describe_area, *point) for point in (origin, destination)]
            route = route_future.result()
            index = index_future.result()
            origin_name, destination_name = (future.result() for future in name_futures)
        directory = deps.directory_loader(deps.supabase)
        return {
            "route": route,
            "index": index,
            "origin_name": origin_name or _fallback_place_name(state["origin_query"], origin, settings, directory),
            "destination_name": destination_name
            or _fallback_place_name(state["destination_query"], destination, settings, directory),
        }

    def assess_risk(state: RouteCheckState) -> RouteCheckState:
        route, index, departure = state["route"], state["index"], state["departure"]
        alternatives = route.alternatives[: max(0, settings.route_max_alternatives)]
        directory = deps.directory_loader(deps.supabase)

        analyses = []
        for candidate in (route, *alternatives):
            analysis = name_segments(analyze_route(candidate, departure, index, settings), directory, settings)
            analyses.append(replace(analysis, reasons=build_reasons(analysis, settings, is_data_limited(analysis, settings))))

        main = analyses[0]
        best = pick_safer_alternative(main, analyses[1:], settings)
        # Dari menit yang DITAMPILKAN (dibulatkan lebih dulu), supaya konsisten dengan duration_minutes tiap rute.
        main_minutes = round(main.duration_s / 60)
        extra_minutes = [round(a.duration_s / 60) - main_minutes for a in analyses[1:]]
        if best is not None:
            note = f"Lebih rendah risikonya dibanding rute utama, {_minutes_phrase(extra_minutes[best])}."
            analyses[best + 1] = replace(analyses[best + 1], reasons=(*analyses[best + 1].reasons, note))
            analyses[0] = main = replace(
                main, reasons=(*main.reasons, f"Tersedia rute alternatif dengan risiko lebih rendah, {_minutes_phrase(extra_minutes[best])}.")
            )

        summaries = tuple(
            AlternativeRoute(
                assessment=assessment_of(alt),
                analysis=alt,
                distance_km=round(alt.distance_m / 1000, 1),
                duration_minutes=round(alt.duration_s / 60),
                extra_minutes=extra,
                is_lowest_risk=index_ == best,
            )
            for index_, (alt, extra) in enumerate(zip(analyses[1:], extra_minutes))
        )
        assessment = assessment_of(main)
        # Log hanya hitungan & status — tanpa teks lokasi/koordinat pengguna.
        logger.info(
            "Cek rute: %d titik cek, %d berdata, %d ruas, status=%s, %d alternatif",
            assessment.areas_checked, assessment.areas_with_data, len(main.segments), assessment.level, len(summaries),
        )
        return {"analysis": main, "assessment": assessment, "alternatives": summaries}

    def advise(state: RouteCheckState) -> RouteCheckState:
        route = state["route"]
        facts = build_narrative_facts(
            state["assessment"],
            state["analysis"],
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
    (layanan rute), atau error database dari pembacaan insiden; API yang memetakannya ke HTTP.
    """
    final_state = build_route_graph(deps).invoke(
        {
            "origin_query": origin,
            "destination_query": destination,
            "departure": departure,
            "include_narrative": include_narrative,
        }
    )
    route, analysis = final_state["route"], final_state["analysis"]
    return RouteCheckResult(
        assessment=final_state["assessment"],
        origin=final_state["origin"],
        destination=final_state["destination"],
        distance_km=round(route.distance_m / 1000, 1),
        duration_minutes=round(route.duration_s / 60),
        departure_time=departure,
        time_buckets=analysis.time_buckets,
        narrative=final_state.get("narrative"),
        origin_name=final_state.get("origin_name"),
        destination_name=final_state.get("destination_name"),
        alternatives=final_state.get("alternatives", ()),
        location_notes=tuple(final_state.get("location_notes", ())),
        analysis=analysis,
    )
