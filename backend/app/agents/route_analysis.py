"""Analisis rute berbasis KEDEKATAN INSIDEN (Safe Route Advisor, REQ-F-030/031/032) — fungsi murni.

Lebih presisi daripada sel grid 1,1 km: rute dijarangkan jadi titik cek tiap ~`route_check_step_meters`
(125 m), tiap titik dihitung terhadap insiden terskor dalam radius `route_incident_radius_meters` (300 m):

    bobot insiden di titik = kebaruan x jarak x kesesuaian jam
      - kebaruan  : 0.5 ** (umur / half-life)  (`recency_weight` yang sama dengan skor heatmap)
      - jarak     : kernel linear (1 di titik, 0 di tepi radius) atau gaussian (`route_incident_kernel`)
      - jam       : bucket jam kejadian == bucket jam TIBA di titik itu -> 1.0; bucket bersebelahan ->
                    `route_incident_adjacent_bucket_weight` (0.5); lainnya diabaikan
    intensitas titik = jumlah bobot -> skor dasar `base_score_from_intensity` (fungsi jenuh & skala yang
    SAMA dengan heatmap) -> dikali pengali musim pada TANGGAL dan JAM tiba di titik itu (`apply_seasonality`)
    -> level (`risk_level_for`: sedang >= 3, tinggi >= 7).

Waktu tiba per titik = waktu berangkat + durasi kumulatif langkah Mapbox, sehingga rute yang melewati
pergantian jam atau tengah malam dinilai dengan bucket & musim yang sesuai PER TITIK (bukan satu jam
untuk seluruh rute).

Titik cek dikelompokkan menurut NAMA JALAN dari langkah (steps) Mapbox: langkah berurutan bernama sama
digabung jadi satu segmen; tanpa nama = "jalan tanpa nama".

STATUS RUTE (deterministik, dari panjang paparan; semua ambang di config):

    berisiko_tinggi : panjang jalur berlevel TINGGI >= route_high_exposure_meters (200 m)
                      ATAU ada titik dengan skor >= route_critical_score_threshold (8.5)
    waspada         : (bukan di atas) ada titik berlevel tinggi (paparan pendek) ATAU panjang jalur berlevel
                      sedang-atau-lebih >= route_medium_exposure_meters (400 m)
    aman            : selain itu

    paparan tinggi | paparan sedang+ | skor maks | status
    ---------------+-----------------+-----------+----------------------------------------------
        >= 200 m   |       any       |   >= 7.0  | berisiko_tinggi
        1-199 m    |       any       |  7.0-8.49 | waspada  (tinggi pendek)
        1-199 m    |       any       |   >= 8.5  | berisiko_tinggi (skor kritis)
          0 m      |    >= 400 m     |  3.0-6.99 | waspada
          0 m      |    1-399 m      |  3.0-6.99 | aman (segmen sedang tetap dicantumkan)
          0 m      |      0 m        |   < 3.0   | aman (lihat data_limited bila tak ada data)

Invarian TC-RTE-001: rute yang melintasi satu titik berskor tinggi TIDAK PERNAH "aman". Untuk rute yang
lebih pendek dari ambang, ambang dibatasi panjang rute (rute pendek yang seluruhnya tinggi tetap
berisiko_tinggi). "aman" berarti tidak ada paparan yang memenuhi syarat DI DATA YANG TERCATAT — bukan jaminan.

KNOWN LIMITATIONS: "tidak ada insiden dekat" dan "belum ada data" tidak sama; `data_coverage` (titik cek
yang punya insiden terskor jam apa pun dalam `route_data_coverage_radius_meters`) mengungkap cakupan data.
Cakupan antar rute alternatif tidak dinormalisasi; alternatif hanya disarankan bila cakupannya sebanding.
PRIVASI: hasil hanya berisi agregat per segmen (jumlah, kategori umum, sebaran bucket jam); koordinat
dan teks insiden individual tidak pernah keluar dari modul ini. Titik PUNCAK skor ruas (lokasi di jalur dengan
skor tertinggi, yang menunjuk letak kluster dalam resolusi ~125 m) hanya dipakai internal untuk menamai
kecamatan; koordinat yang dikeluarkan untuk ruas adalah TITIK TENGAH ruas di jalur.
"""

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.agents.incident_index import IncidentIndex, IndexedIncident
from app.agents.risk_agent import (
    JELANG_RAMADAN,
    SELAMA_RAMADAN,
    TIME_BUCKET_HOURS,
    apply_seasonality,
    base_score_from_intensity,
    recency_weight,
    risk_level_for,
    time_bucket_of,
    to_wib,
)
from app.core.config import Settings
from app.core.directions import RouteGeometry, RouteStep
from app.core.geo import haversine_meters

ROUTE_AMAN = "aman"
ROUTE_WASPADA = "waspada"
ROUTE_BERISIKO_TINGGI = "berisiko_tinggi"
LEVEL_RANK = {ROUTE_AMAN: 0, ROUTE_WASPADA: 1, ROUTE_BERISIKO_TINGGI: 2}
UNNAMED_ROAD = "jalan tanpa nama"

_BUCKETS = [bucket for bucket, _, _ in TIME_BUCKET_HOURS]
_METERS_PER_DEGREE = 111_320.0


# ------------------------------------------------------------------ bobot (murni)


def bucket_weight(incident_bucket: str, point_bucket: str, adjacent_weight: float) -> float:
    """1.0 bila bucket jam sama, `adjacent_weight` bila bersebelahan (siklus 24 jam: malam ~ dini hari), selain itu 0."""
    if incident_bucket == point_bucket:
        return 1.0
    gap = abs(_BUCKETS.index(incident_bucket) - _BUCKETS.index(point_bucket))
    return adjacent_weight if gap in (1, len(_BUCKETS) - 1) else 0.0


def distance_weight(distance_m: float, radius_m: float, kernel: str) -> float:
    """Bobot jarak 1..0. linear: 1 - d/R. gaussian: sigma = R/3 (bobot di tepi radius ~1%)."""
    if distance_m >= radius_m:
        return 0.0
    ratio = distance_m / radius_m
    if kernel == "gaussian":
        return math.exp(-4.5 * ratio * ratio)
    return 1.0 - ratio


# -------------------------------------------------------------- geometri (murni)


@dataclass(frozen=True)
class RouteSample:
    latitude: float
    longitude: float
    fraction: float  # posisi di sepanjang polyline, 0.0 (awal) sampai 1.0 (akhir)


def polyline_length(points: Sequence[tuple[float, float]]) -> float:
    return sum(haversine_meters(a, b) for a, b in zip(points, points[1:]))


def sample_route(points: Sequence[tuple[float, float]], step_meters: float, max_samples: int) -> list[RouteSample]:
    """Jarangkan polyline jadi titik cek tiap `step_meters` (selalu termasuk titik awal & akhir). Polyline
    yang terlalu panjang dijarangkan supaya jumlah titik tidak melebihi ~`max_samples`."""
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


def polyline_midpoint(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Titik di tengah panjang polyline (bukan vertex tengah)."""
    if len(points) == 1:
        return points[0]
    total = polyline_length(points)
    walked = 0.0
    for a, b in zip(points, points[1:]):
        length = haversine_meters(a, b)
        if walked + length >= total / 2 and length > 0:
            ratio = (total / 2 - walked) / length
            return a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio
        walked += length
    return points[-1]


def simplify_polyline(points: Sequence[tuple[float, float]], tolerance_m: float) -> tuple[tuple[float, float], ...]:
    """Douglas-Peucker (iteratif): buang titik yang menyimpang < `tolerance_m` dari garis lurus. Titik awal
    dan akhir selalu dipertahankan, urutan tetap."""
    n = len(points)
    if n <= 2 or tolerance_m <= 0:
        return tuple(points)
    lat0 = points[0][0]
    kx = _METERS_PER_DEGREE * math.cos(math.radians(lat0))
    xy = [(lon * kx, lat * _METERS_PER_DEGREE) for lat, lon in points]

    def deviation(index: int, start: int, end: int) -> float:
        (x1, y1), (x2, y2), (px, py) = xy[start], xy[end], xy[index]
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        start, end = stack.pop()
        far_index, far_dev = -1, 0.0
        for index in range(start + 1, end):
            dev = deviation(index, start, end)
            if dev > far_dev:
                far_index, far_dev = index, dev
        if far_dev > tolerance_m:
            keep[far_index] = True
            stack.append((start, far_index))
            stack.append((far_index, end))
    return tuple(point for point, kept in zip(points, keep) if kept)


# ------------------------------------------------------------------- data analisis


@dataclass(frozen=True)
class CheckPoint:
    latitude: float
    longitude: float
    along_m: float  # jarak dari awal rute
    arrival: datetime  # perkiraan waktu tiba (WIB)
    bucket: str  # bucket jam tiba
    step_index: int
    interval_m: float = 0.0  # panjang jalur yang diwakili titik ini (untuk menghitung panjang paparan)


@dataclass(frozen=True)
class PointScore:
    score: float  # skor AKHIR (sudah dikali pengali musim)
    level: str  # rendah / sedang / tinggi
    incidents: tuple[IndexedIncident, ...]  # insiden yang berkontribusi (bobot > 0); TIDAK keluar dari modul ini
    covered: bool  # ada insiden terskor (jam apa pun) dalam radius cakupan
    season: str | None


@dataclass(frozen=True)
class Segment:
    """Satu ruas jalan (langkah berurutan bernama sama). Hanya agregat — tanpa insiden individual."""

    index: int
    road_name: str
    start_m: float
    end_m: float
    geometry: tuple[tuple[float, float], ...]  # (lintang, bujur), sudah dijarangkan
    max_score: float
    level: str
    incident_count: int
    dominant_category: str | None
    incident_hours: dict[str, int]  # bucket jam kejadian historis -> jumlah insiden
    has_nearby_data: bool
    peak_bucket: str
    peak_latitude: float  # titik cek dengan skor tertinggi: HANYA untuk menamai kecamatan, tidak pernah dikeluarkan
    peak_longitude: float
    mid_latitude: float  # titik tengah ruas di jalur: satu-satunya koordinat ruas yang boleh dikeluarkan
    mid_longitude: float
    high_exposure_m: float
    medium_exposure_m: float  # sedang ATAU tinggi
    place_name: str | None = None  # "Kec. X" (diisi agen dari tabel areas)

    @property
    def length_m(self) -> float:
        return self.end_m - self.start_m


@dataclass(frozen=True)
class RouteAnalysis:
    status: str
    max_score: float
    high_exposure_m: float
    medium_exposure_m: float
    any_high: bool
    checked_points: int
    covered_points: int
    incident_count: int
    segments: tuple[Segment, ...]
    geometry: tuple[tuple[float, float], ...]  # (lintang, bujur), sudah dijarangkan
    time_buckets: tuple[str, ...]
    seasons: tuple[str, ...]  # fase musim yang dipakai (jelang/selama Ramadan) bila ada
    distance_m: float
    duration_s: float
    reasons: tuple[str, ...] = field(default=())

    @property
    def data_coverage(self) -> float:
        return round(self.covered_points / self.checked_points, 3) if self.checked_points else 0.0


# ------------------------------------------------------------------- titik cek


@dataclass(frozen=True)
class _Step:
    name: str
    points: tuple[tuple[float, float], ...]
    length_m: float
    duration_s: float
    start_m: float
    start_s: float


def _effective_steps(route: RouteGeometry) -> list[_Step]:
    """Langkah rute dengan jarak/durasi kumulatif. Durasi diskalakan ke durasi total rute; tanpa langkah
    dari Mapbox, seluruh rute diperlakukan sebagai satu jalur tanpa nama."""
    raw = route.steps or (RouteStep("", route.distance_m, route.duration_s, route.points),)
    lengths = [polyline_length(step.points) for step in raw]
    total_len = sum(lengths) or 1.0
    total_dur = sum(step.duration_s for step in raw)
    steps: list[_Step] = []
    cum_m = cum_s = 0.0
    for step, length in zip(raw, lengths):
        duration = (
            step.duration_s * route.duration_s / total_dur if total_dur > 0 else route.duration_s * length / total_len
        )
        steps.append(_Step(step.name or UNNAMED_ROAD, step.points, length, duration, cum_m, cum_s))
        cum_m += length
        cum_s += duration
    return steps


def build_check_points(steps: list[_Step], departure: datetime, settings: Settings) -> list[CheckPoint]:
    total = sum(step.length_m for step in steps)
    spacing = max(float(settings.route_check_step_meters), total / max(1, settings.route_max_samples - 1))
    departure = to_wib(departure)

    points: list[CheckPoint] = []
    for index, step in enumerate(steps):
        samples = sample_route(step.points, spacing, 10**9)
        if index > 0 and len(samples) > 1:
            samples = samples[1:]  # titik sambungan sudah dimiliki langkah sebelumnya
        for sample in samples:
            arrival = departure + timedelta(seconds=step.start_s + sample.fraction * step.duration_s)
            points.append(
                CheckPoint(
                    sample.latitude, sample.longitude, step.start_m + sample.fraction * step.length_m,
                    arrival, time_bucket_of(arrival), index,
                )
            )

    # Panjang jalur yang diwakili tiap titik = setengah jarak ke tetangga kiri + kanan (jumlah = panjang rute).
    sized: list[CheckPoint] = []
    for i, point in enumerate(points):
        before = point.along_m - points[i - 1].along_m if i > 0 else 0.0
        after = points[i + 1].along_m - point.along_m if i + 1 < len(points) else 0.0
        interval = (before + after) / 2 if (i > 0 and i + 1 < len(points)) else max(before, after) / 2
        sized.append(replace(point, interval_m=interval))
    return sized


def score_point(point: CheckPoint, index: IncidentIndex, departure: datetime, settings: Settings) -> PointScore:
    radius = settings.route_incident_radius_meters
    nearby = index.near(point.latitude, point.longitude, radius)
    intensity = 0.0
    contributors: list[IndexedIncident] = []
    for incident, distance in nearby:
        weight = bucket_weight(incident.bucket, point.bucket, settings.route_incident_adjacent_bucket_weight)
        if weight <= 0:
            continue
        weight *= distance_weight(distance, radius, settings.route_incident_kernel)
        weight *= recency_weight(incident.occurred_at, to_wib(departure), settings.risk_recency_half_life_days)
        if weight <= 0:
            continue
        intensity += weight
        contributors.append(incident)

    base = base_score_from_intensity(intensity, settings) if intensity > 0 else 0.0
    seasonal = apply_seasonality(base, to_wib(point.arrival).date(), point.bucket, settings)
    covered = bool(nearby) or index.any_within(point.latitude, point.longitude, settings.route_data_coverage_radius_meters)
    return PointScore(seasonal.score, seasonal.level, tuple(contributors), covered, seasonal.phase)


# -------------------------------------------------------------------- agregasi


def _unique_consecutive(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for point in points:
        if not result or result[-1] != point:
            result.append(point)
    return result


def decide_status(
    high_exposure_m: float,
    medium_exposure_m: float,
    any_high: bool,
    max_score: float,
    route_length_m: float,
    settings: Settings,
) -> str:
    """Status rute dari paparan (lihat tabel di docstring modul). Ambang dibatasi panjang rute."""
    high_threshold = min(float(settings.route_high_exposure_meters), route_length_m)
    medium_threshold = min(float(settings.route_medium_exposure_meters), route_length_m)
    if (any_high and high_exposure_m >= high_threshold) or max_score >= settings.route_critical_score_threshold:
        return ROUTE_BERISIKO_TINGGI
    if any_high or (medium_exposure_m > 0 and medium_exposure_m >= medium_threshold):
        return ROUTE_WASPADA
    return ROUTE_AMAN


def analyze_route(route: RouteGeometry, departure: datetime, index: IncidentIndex, settings: Settings) -> RouteAnalysis:
    """Nilai satu rute terhadap indeks insiden (fungsi murni; tanpa jaringan/DB)."""
    steps = _effective_steps(route)
    points = build_check_points(steps, departure, settings)
    scores = [score_point(point, index, departure, settings) for point in points]

    # Kelompokkan langkah berurutan bernama sama menjadi satu ruas jalan.
    groups: list[list[int]] = []
    for i, step in enumerate(steps):
        if groups and steps[groups[-1][0]].name.casefold() == step.name.casefold():
            groups[-1].append(i)
        else:
            groups.append([i])

    tolerance = settings.route_geometry_tolerance_meters
    segments: list[Segment] = []
    all_incidents: dict[int, IndexedIncident] = {}
    for seg_index, group in enumerate(groups):
        group_steps = set(group)
        members = [(p, s) for p, s in zip(points, scores) if p.step_index in group_steps]
        incidents = {inc.ident: inc for _, s in members for inc in s.incidents}
        all_incidents.update(incidents)
        peak_point, peak_score = max(members, key=lambda item: item[1].score)  # urutan menang saat seri
        categories = Counter(i.category for i in incidents.values() if i.category)
        dominant = min(categories, key=lambda c: (-categories[c], c)) if categories else None
        geometry = simplify_polyline(
            _unique_consecutive([pt for i in group for pt in steps[i].points]), tolerance
        )
        mid = polyline_midpoint(geometry)
        segments.append(
            Segment(
                index=seg_index,
                road_name=steps[group[0]].name,
                start_m=steps[group[0]].start_m,
                end_m=steps[group[-1]].start_m + steps[group[-1]].length_m,
                geometry=geometry,
                max_score=peak_score.score,
                level=risk_level_for(peak_score.score, settings),
                incident_count=len(incidents),
                dominant_category=dominant,
                incident_hours=dict(Counter(i.bucket for i in incidents.values())),
                has_nearby_data=any(s.covered for _, s in members),
                peak_bucket=peak_point.bucket,
                peak_latitude=peak_point.latitude,
                peak_longitude=peak_point.longitude,
                mid_latitude=mid[0],
                mid_longitude=mid[1],
                high_exposure_m=sum(p.interval_m for p, s in members if s.level == "tinggi"),
                medium_exposure_m=sum(p.interval_m for p, s in members if s.level in ("sedang", "tinggi")),
            )
        )

    total_length = sum(step.length_m for step in steps)
    high_m = sum(s.high_exposure_m for s in segments)
    medium_m = sum(s.medium_exposure_m for s in segments)
    max_score = max((s.score for s in scores), default=0.0)
    any_high = any(s.level == "tinggi" for s in scores)
    route_points = _unique_consecutive([pt for step in steps for pt in step.points])
    return RouteAnalysis(
        status=decide_status(high_m, medium_m, any_high, max_score, total_length, settings),
        max_score=max_score,
        high_exposure_m=high_m,
        medium_exposure_m=medium_m,
        any_high=any_high,
        checked_points=len(points),
        covered_points=sum(1 for s in scores if s.covered),
        incident_count=len(all_incidents),
        segments=tuple(segments),
        geometry=simplify_polyline(route_points, tolerance),
        time_buckets=tuple(dict.fromkeys(p.bucket for p in points)),
        seasons=tuple(dict.fromkeys(s.season for s in scores if s.season)),
        distance_m=total_length,
        duration_s=route.duration_s,
    )


# ------------------------------------------------------------------- alasan (id)


def _bucket_label(bucket: str) -> str:
    return bucket.replace("_", " ")


def _round_m(value: float) -> int:
    return max(10, int(round(value / 10.0)) * 10)


def build_reasons(analysis: RouteAnalysis, settings: Settings, data_limited: bool) -> tuple[str, ...]:
    """Alasan singkat berbahasa Indonesia yang NETRAL dan deterministik dari data (REQ-NF-141): tidak
    sensasional, tidak menjanjikan keamanan, tanpa koordinat atau kronologi kejadian."""
    reasons: list[str] = []
    if analysis.status == ROUTE_BERISIKO_TINGGI:
        if analysis.high_exposure_m > 0:
            reasons.append(
                f"Sekitar {_round_m(analysis.high_exposure_m)} m jalur melewati area berskor kerawanan tinggi pada jam perjalanan."
            )
        else:
            reasons.append("Ada titik di jalur dengan skor kerawanan sangat tinggi pada jam perjalanan.")
    elif analysis.status == ROUTE_WASPADA:
        if analysis.any_high:
            reasons.append("Ada bagian pendek jalur yang melewati area berskor kerawanan tinggi (di bawah batas rute berisiko tinggi).")
        if analysis.medium_exposure_m > 0 and not analysis.any_high:
            reasons.append(
                f"Sekitar {_round_m(analysis.medium_exposure_m)} m jalur melewati area berskor kerawanan sedang atau lebih."
            )
    else:
        reasons.append(
            "Tidak ada bagian jalur yang melewati area berskor sedang atau tinggi pada jam perjalanan, "
            "berdasarkan data kejadian yang tercatat."
        )

    flagged = sorted((s for s in analysis.segments if s.level in ("tinggi", "sedang")), key=lambda s: -s.max_score)[:3]
    for segment in flagged:
        place = f" ({segment.place_name})" if segment.place_name else ""
        clauses = [
            f"Melewati {segment.road_name}{place}: {segment.incident_count} kejadian tercatat dalam radius "
            f"{settings.route_incident_radius_meters} m dari jalur"
        ]
        if segment.dominant_category and segment.dominant_category != "lainnya":
            clauses.append(f"kategori terbanyak {segment.dominant_category}")
        top_hours = [b for b, _ in sorted(segment.incident_hours.items(), key=lambda kv: (-kv[1], kv[0]))[:2]]
        if top_hours:
            clauses.append("paling sering pada jam " + " dan ".join(_bucket_label(b) for b in top_hours))
        reasons.append(", ".join(clauses) + f". Anda diperkirakan melintas pada jam {_bucket_label(segment.peak_bucket)}.")

    if JELANG_RAMADAN in analysis.seasons or SELAMA_RAMADAN in analysis.seasons:
        phase = "selama" if SELAMA_RAMADAN in analysis.seasons else "menjelang"
        reasons.append(f"Skor disesuaikan karena perjalanan jatuh pada periode {phase} Ramadan.")

    if data_limited:
        reasons.append("Belum ada data kejadian di sekitar rute ini; hasil ini bukan jaminan aman.")
    elif analysis.status == ROUTE_AMAN:
        reasons.append(
            f"Hasil berdasarkan data kejadian yang tercatat dan bukan jaminan keamanan; {round(analysis.data_coverage * 100)}% "
            f"titik pemeriksaan memiliki data kejadian di sekitarnya."
        )
    return tuple(reasons)


# ---------------------------------------------------------------- alternatif


def is_data_limited(analysis: RouteAnalysis, settings: Settings) -> bool:
    return analysis.checked_points == 0 or analysis.data_coverage <= settings.route_limited_coverage_threshold


def _clearly_lower(candidate: RouteAnalysis, reference: RouteAnalysis, min_gain: float) -> bool:
    if LEVEL_RANK[candidate.status] != LEVEL_RANK[reference.status]:
        return LEVEL_RANK[candidate.status] < LEVEL_RANK[reference.status]
    return candidate.max_score <= reference.max_score - min_gain


def pick_safer_alternative(
    main: RouteAnalysis, alternatives: Sequence[RouteAnalysis], settings: Settings
) -> int | None:
    """Indeks alternatif yang layak disarankan, atau None. Syarat (semuanya):
    - jelas lebih rendah: level lebih rendah, atau level sama dengan skor maks lebih rendah >= `route_alternative_min_score_gain`;
    - datanya SEBANDING: punya data dan cakupannya >= `route_alternative_min_coverage_ratio` x cakupan rute utama
      (alternatif yang tampak "lebih aman" hanya karena kurang data TIDAK disarankan);
    - tidak terlalu lebih lama: tambahan waktu <= `route_alternative_max_extra_time_ratio` x durasi rute utama.
    Di antara yang lolos: level terendah, lalu skor terendah, lalu tercepat."""
    qualified = [
        i
        for i, alt in enumerate(alternatives)
        if not is_data_limited(alt, settings)
        and alt.data_coverage >= settings.route_alternative_min_coverage_ratio * main.data_coverage
        and alt.duration_s - main.duration_s <= settings.route_alternative_max_extra_time_ratio * main.duration_s
        and _clearly_lower(alt, main, settings.route_alternative_min_score_gain)
    ]
    return min(
        qualified,
        key=lambda i: (LEVEL_RANK[alternatives[i].status], alternatives[i].max_score, alternatives[i].duration_s),
        default=None,
    )
