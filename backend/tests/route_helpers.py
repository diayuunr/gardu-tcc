"""Pembantu bersama test rute: rute lurus ke utara dengan langkah bernama, dan insiden pada jarak tertentu
dari rute (dalam meter). Bukan test; diimpor oleh test_route_*.py."""

import math
from datetime import datetime

from app.agents.incident_index import IncidentIndex, IndexedIncident
from app.agents.risk_agent import WIB, time_bucket_of
from app.core.directions import RouteGeometry, RouteStep
from app.core.geo import haversine_meters

M = 1 / (math.pi * 6_371_000 / 180)  # derajat lintang per meter (jari-jari bumi yang sama dengan haversine_meters)
BASE_LAT, BASE_LON = -7.7600, 110.3800  # titik awal rute (Sleman, sekitar Jl. Kaliurang), rute menuju UTARA
NIGHT = datetime(2026, 9, 20, 22, 0, tzinfo=WIB)  # bucket "malam", di luar musim Ramadan
RECENT = datetime(2026, 9, 10, 22, 0, tzinfo=WIB)  # 10 hari sebelum NIGHT: bobot kebaruan ~1


def point_at(along_m: float, east_m: float = 0.0) -> tuple[float, float]:
    lat = BASE_LAT + along_m * M
    return lat, BASE_LON + east_m * M / math.cos(math.radians(lat))


def road(name: str, start_m: float, end_m: float, duration_s: float, points: int = 2, east_m: float = 0.0) -> RouteStep:
    """Satu langkah lurus ke utara dari `start_m` ke `end_m` (jarak dari awal rute), `east_m` meter di timur."""
    coords = tuple(point_at(start_m + (end_m - start_m) * i / (points - 1), east_m) for i in range(points))
    return RouteStep(name, haversine_meters(coords[0], coords[-1]), duration_s, coords)


def route_of(*steps: RouteStep, alternatives=()) -> RouteGeometry:
    points: list[tuple[float, float]] = []
    for step in steps:
        for p in step.points:
            if not points or points[-1] != p:
                points.append(p)
    return RouteGeometry(
        points=tuple(points),
        distance_m=sum(s.distance_m for s in steps),
        duration_s=sum(s.duration_s for s in steps),
        alternatives=tuple(alternatives),
        steps=tuple(steps),
    )


def incident(
    ident: int,
    along_m: float,
    east_m: float = 0.0,
    when: datetime = RECENT,
    category: str = "klitih",
) -> IndexedIncident:
    lat, lon = point_at(along_m, east_m)
    return IndexedIncident(ident, lat, lon, when, time_bucket_of(when), category)


def index_of(*incidents: IndexedIncident) -> IncidentIndex:
    return IncidentIndex(incidents)


def cluster(count: int, along_m: float, east_m: float = 0.0, start_ident: int = 0, **kwargs) -> list[IndexedIncident]:
    """`count` insiden pada satu titik (di rute bila east_m = 0)."""
    return [incident(start_ident + i, along_m, east_m, **kwargs) for i in range(count)]
