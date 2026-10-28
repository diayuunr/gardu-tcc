"""Skenario uji SINTETIS untuk contoh respons /route/check (dipakai test_route_e2e.py dan skrip pembuat contoh
di docs/API.md). Nama jalan/kecamatan dan koordinat jalur mengikuti peta nyata secara kasar, tetapi INSIDEN-nya
karangan: bukan data kejadian sebenarnya. Nama kecamatan berasal dari backend/data/areas_rows.csv.
"""

from datetime import datetime
from pathlib import Path

from app.agents.incident_index import IncidentIndex, IndexedIncident
from app.agents.risk_agent import WIB, time_bucket_of
from app.agents.route_agent import PlaceQuery, RouteAgentDeps
from app.core.areas import Area, AreaDirectory
from app.core.directions import RouteGeometry, RouteStep
from app.core.geo import haversine_meters
from app.scripts import load_areas

DEPARTURE = datetime(2026, 9, 20, 22, 0, tzinfo=WIB)  # malam, di luar musim Ramadan
ORIGIN = PlaceQuery(latitude=-7.7829, longitude=110.3671)  # sekitar Tugu Yogyakarta
DESTINATION = PlaceQuery(latitude=-7.7300, longitude=110.4060)  # Jl. Ring Road Utara, Condongcatur

_CSV = Path(__file__).resolve().parent.parent / "data" / "areas_rows.csv"


def _step(name, duration_s, *waypoints) -> RouteStep:
    distance = sum(haversine_meters(a, b) for a, b in zip(waypoints, waypoints[1:]))
    return RouteStep(name, distance, duration_s, tuple(waypoints))


def _route(*steps: RouteStep, alternatives=()) -> RouteGeometry:
    points: list = []
    for step in steps:
        for p in step.points:
            if not points or points[-1] != p:
                points.append(p)
    return RouteGeometry(
        tuple(points), sum(s.distance_m for s in steps), sum(s.duration_s for s in steps), tuple(alternatives), tuple(steps)
    )


def sample_route() -> RouteGeometry:
    alternative = _route(
        _step("Jalan Mangkubumi", 150, (-7.7829, 110.3671), (-7.7790, 110.3640), (-7.7700, 110.3610)),
        _step("Jalan Magelang", 330, (-7.7700, 110.3610), (-7.7560, 110.3590), (-7.7420, 110.3640)),
        _step("Ring Road Utara", 300, (-7.7420, 110.3640), (-7.7360, 110.3860), (-7.7330, 110.4000)),
        _step("", 90, (-7.7330, 110.4000), (-7.7300, 110.4060)),
    )
    return _route(
        _step("Jalan Cik Di Tiro", 150, (-7.7829, 110.3671), (-7.7790, 110.3715), (-7.7745, 110.3750)),
        _step("Jalan Kaliurang", 200, (-7.7745, 110.3750), (-7.7670, 110.3800), (-7.7600, 110.3860)),
        _step("Jalan Kaliurang", 260, (-7.7600, 110.3860), (-7.7500, 110.3890), (-7.7400, 110.3920)),
        _step("Ring Road Utara", 170, (-7.7400, 110.3920), (-7.7360, 110.3990), (-7.7330, 110.4025)),
        _step("", 50, (-7.7330, 110.4025), (-7.7300, 110.4060)),
        alternatives=[alternative],
    )


def _incidents() -> IndexedIncident:
    def make(ident, lat, lon, when, category):
        return IndexedIncident(ident, lat, lon, when, time_bucket_of(when), category)

    night = lambda day, hour=22: datetime(2026, 9, day, hour, 0, tzinfo=WIB)  # noqa: E731
    return [
        # Kluster di sekitar Jl. Kaliurang (bagian utara): beberapa kejadian di jam malam & dini hari.
        make(1, -7.7502, 110.3891, night(10), "klitih"),
        make(2, -7.7498, 110.3888, night(5, 23), "klitih"),
        make(3, -7.7507, 110.3895, night(2), "penyerangan"),
        make(4, -7.7494, 110.3886, night(1, 1), "penyerangan"),
        make(5, -7.7511, 110.3899, night(8, 2), "klitih"),
        make(6, -7.7490, 110.3884, night(9), "bentrok antar kelompok"),
        make(7, -7.7515, 110.3902, night(7, 23), "klitih"),
        make(8, -7.7486, 110.3880, night(4), "penyerangan"),
        make(9, -7.7503, 110.3893, night(3, 21), "klitih"),
        # Dua kejadian di Ring Road Utara.
        make(10, -7.7362, 110.3995, night(6), "begal/penodongan"),
        make(11, -7.7366, 110.3999, night(2, 23), "begal/penodongan"),
        # Data tersebar di jalur alternatif (satu kejadian siang hari di Jl. Magelang): cakupan data sebanding.
        make(12, -7.7563, 110.3594, night(3, 13), "kejadian mencurigakan"),
        make(13, -7.7430, 110.3650, night(8, 13), "lainnya"),
    ]


def sample_directory() -> AreaDirectory:
    rows = load_areas.read_areas_csv(_CSV).rows
    return AreaDirectory([Area(r.kode, r.nama, r.tingkat, r.parent_kode, r.latitude, r.longitude) for r in rows])


def sample_deps() -> RouteAgentDeps:
    index = IncidentIndex(_incidents())
    route = sample_route()
    directory = sample_directory()
    return RouteAgentDeps(
        supabase=None,
        fetch_route=lambda _o, _d: route,
        describe_area=lambda _lat, _lon: None,
        narrate=lambda _facts: None,
        incident_loader=lambda _s: index,
        directory_loader=lambda _s: directory,
    )


SAMPLE_INCIDENTS = _incidents()
