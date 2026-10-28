from datetime import datetime
from types import SimpleNamespace

import pytest

from app.agents.risk_agent import WIB, locate_area
from app.agents.route_agent import (
    ROUTE_AMAN,
    ROUTE_BERISIKO_TINGGI,
    ROUTE_WASPADA,
    PlaceQuery,
    RouteAgentDeps,
    RoutePointError,
    crossed_cells,
    haversine_meters,
    run_route_check,
    sample_route,
)
from app.core.config import get_settings
from app.core.directions import RouteGeometry, RouteNotFound

# Gedongkuning (seed SRS) -> Tugu Yogyakarta: rute lurus buatan ~4,8 km, 21 menit.
GEDONGKUNING = (-7.812995, 110.39872)
TUGU = (-7.7830, 110.3670)
START_CELL = locate_area(*GEDONGKUNING, 0.01)[2]  # "Area -7.815, 110.395"
NIGHT = datetime(2026, 9, 20, 22, 0, tzinfo=WIB)  # bucket "malam"
MORNING = datetime(2026, 9, 20, 9, 0, tzinfo=WIB)  # bucket "pagi"
ALL_BUCKETS = ("dini_hari", "pagi", "siang", "sore", "malam")


@pytest.fixture(autouse=True)
def mapbox_configured(monkeypatch):
    """Token palsu supaya titik berupa TEKS lolos pengecekan konfigurasi (geocode di-fake)."""
    monkeypatch.setenv("MAPBOX_TOKEN", "dummy-token-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _straight_route(origin=GEDONGKUNING, destination=TUGU, duration_s=1260.0) -> RouteGeometry:
    midpoint = ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2)
    return RouteGeometry(
        points=(origin, midpoint, destination),
        distance_m=haversine_meters(origin, destination),
        duration_s=duration_s,
    )


class _ScoresSupabase:
    """Supabase palsu untuk `risk_scores`: mendukung select().in_().in_().execute()."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = 0

    def table(self, name):
        assert name == "risk_scores"
        return _ScoresQuery(self)


class _ScoresQuery:
    def __init__(self, owner):
        self._owner, self._filters = owner, []

    def select(self, _columns):
        return self

    def in_(self, column, values):
        self._filters.append((column, set(values)))
        return self

    def execute(self):
        self._owner.queries += 1
        matched = [r for r in self._owner.rows if all(r[c] in values for c, values in self._filters)]
        return SimpleNamespace(data=matched)


def _score_rows(area_name, level, score, buckets=ALL_BUCKETS):
    return [
        {"area_name": area_name, "time_bucket": bucket, "risk_score": score, "risk_level": level}
        for bucket in buckets
    ]


def _deps(rows, *, route=None, narrate=None, describe=lambda _lat, _lon: "Kotagede", geocode=None):
    return RouteAgentDeps(
        supabase=_ScoresSupabase(rows),
        geocode=geocode or (lambda text: GEDONGKUNING if "asal" in text else TUGU),
        fetch_route=lambda _origin, _destination: route or _straight_route(),
        describe_area=describe,
        narrate=narrate or (lambda _facts: None),
    )


COORDS_FROM = PlaceQuery(latitude=GEDONGKUNING[0], longitude=GEDONGKUNING[1])
COORDS_TO = PlaceQuery(latitude=TUGU[0], longitude=TUGU[1])


# ------------------------------------------------ TC-RTE-001 / REQ-F-030, 031, 032


def test_route_through_high_risk_area_is_flagged_high_and_lists_area_to_avoid():
    deps = _deps(_score_rows(START_CELL, "tinggi", 7.6))

    result = run_route_check(deps, COORDS_FROM, COORDS_TO, NIGHT)

    assessment = result.assessment
    assert assessment.level == ROUTE_BERISIKO_TINGGI  # TIDAK PERNAH "aman" (pass criteria TC-RTE-001)
    assert assessment.max_risk_score == 7.6
    avoid = [a for a in assessment.flagged_areas if a.risk_level == "tinggi"]
    assert [(a.area_name, a.place_name) for a in avoid] == [(START_CELL, "Kotagede")]  # REQ-F-032
    assert (avoid[0].latitude, avoid[0].longitude) == (-7.815, 110.395)  # pusat sel, bukan titik pengguna
    assert result.distance_km == pytest.approx(haversine_meters(GEDONGKUNING, TUGU) / 1000, abs=0.1)
    assert result.duration_minutes == 21
    # Titik yang benar-benar dipakai diberi nama area, supaya hasil geocoding nama tempat bisa dicek pengguna.
    assert (result.origin_name, result.destination_name) == ("Kotagede", "Kotagede")


def test_medium_only_route_is_waspada_and_route_without_any_data_is_aman_with_coverage_shown():
    medium = run_route_check(_deps(_score_rows(START_CELL, "sedang", 4.2)), COORDS_FROM, COORDS_TO, NIGHT)
    assert medium.assessment.level == ROUTE_WASPADA
    assert [a.risk_level for a in medium.assessment.flagged_areas] == ["sedang"]

    empty = run_route_check(_deps([]), COORDS_FROM, COORDS_TO, NIGHT)
    assert empty.assessment.level == ROUTE_AMAN
    assert empty.assessment.areas_with_data == 0  # transparan: "aman" di sini = belum ada data
    assert empty.assessment.areas_checked >= 3


def test_score_is_read_for_the_time_the_route_is_travelled_not_another_hour():
    deps = _deps(_score_rows(START_CELL, "tinggi", 7.6, buckets=("malam",)))

    at_night = run_route_check(deps, COORDS_FROM, COORDS_TO, NIGHT)
    in_the_morning = run_route_check(deps, COORDS_FROM, COORDS_TO, MORNING)

    assert at_night.assessment.level == ROUTE_BERISIKO_TINGGI
    assert in_the_morning.assessment.level == ROUTE_AMAN  # skor "malam" tidak berlaku untuk pagi


def test_route_crossing_an_hour_boundary_uses_the_matching_bucket_per_segment():
    """Berangkat 17.50, tiba ~18.11: awal rute = 'sore', ujung rute = 'malam'."""
    settings = get_settings()
    departure = datetime(2026, 9, 20, 17, 50, tzinfo=WIB)
    route = _straight_route()

    cells = crossed_cells(sample_route(route.points, 250, 400), departure, route.duration_s, settings)

    assert cells[0].time_bucket == "sore"
    assert cells[-1].time_bucket == "malam"
    assert {c.time_bucket for c in cells} == {"sore", "malam"}


# ------------------------------------------------------------------ pengambilan sampel


def test_sample_route_spacing_endpoints_and_cap():
    route = _straight_route()
    samples = sample_route(route.points, 250, 400)
    assert samples[0].fraction == 0.0 and samples[-1].fraction == 1.0
    assert len(samples) == pytest.approx(route.distance_m / 250, abs=3)

    long_route = ((-7.5, 110.3), (-8.0, 110.3))  # ~55 km
    capped = sample_route(long_route, 250, 100)
    assert len(capped) <= 101  # dijarangkan supaya tidak melebihi batas titik cek
    assert capped[-1].latitude == pytest.approx(-8.0)


def test_many_cells_are_fetched_in_chunks_without_losing_any_score():
    long_route = RouteGeometry(points=((-7.60, 110.30), (-8.05, 110.30)), distance_m=50000.0, duration_s=3600.0)
    cell_names = {locate_area(lat, 110.30, 0.01)[2] for lat in [-7.60 - i * 0.005 for i in range(91)]}
    rows = [row for name in cell_names for row in _score_rows(name, "sedang", 4.0)]
    deps = _deps(rows, route=long_route)

    result = run_route_check(deps, PlaceQuery(latitude=-7.60, longitude=110.30), PlaceQuery(latitude=-8.05, longitude=110.30), NIGHT)

    assert deps.supabase.queries >= 2  # lebih dari satu chunk area
    assert result.assessment.areas_with_data == result.assessment.areas_checked > 40
    assert result.assessment.level == ROUTE_WASPADA


# ------------------------------------------------------------------- narasi & error


def test_narrative_only_requested_and_only_for_non_safe_routes():
    facts_seen = []

    def narrate(facts):
        facts_seen.append(facts)
        return "Rute melewati area yang perlu diwaspadai."

    rows = _score_rows(START_CELL, "tinggi", 7.6)

    default = run_route_check(_deps(rows, narrate=narrate), COORDS_FROM, COORDS_TO, NIGHT)
    assert default.narrative is None and facts_seen == []  # default: tanpa narasi

    asked = run_route_check(_deps(rows, narrate=narrate), COORDS_FROM, COORDS_TO, NIGHT, include_narrative=True)
    assert asked.narrative == "Rute melewati area yang perlu diwaspadai."
    facts = facts_seen[0]
    assert facts.route_level == ROUTE_BERISIKO_TINGGI and facts.avoid_places == ("Kotagede",)
    assert "Area -7." not in repr(facts)  # hanya nama area, bukan label/koordinat grid

    safe = run_route_check(_deps([], narrate=narrate), COORDS_FROM, COORDS_TO, NIGHT, include_narrative=True)
    assert safe.narrative is None and len(facts_seen) == 1  # rute aman tidak memanggil narasi


def test_invalid_points_raise_clear_errors_and_route_failures_propagate():
    text = PlaceQuery(text="asal")

    with pytest.raises(RoutePointError, match="asal.*luar wilayah Yogyakarta"):
        run_route_check(_deps([]), PlaceQuery(latitude=-6.2, longitude=106.8), COORDS_TO, NIGHT)  # Jakarta

    with pytest.raises(RoutePointError, match="tujuan tidak ditemukan"):
        run_route_check(_deps([], geocode=lambda _text: None), COORDS_FROM, PlaceQuery(text="tempat ngawur"), NIGHT)

    assert run_route_check(_deps([]), text, COORDS_TO, NIGHT).origin == GEDONGKUNING  # teks di-geocode

    def no_route(_origin, _destination):
        raise RouteNotFound("tidak ada rute")

    deps = _deps([])
    deps.fetch_route = no_route
    with pytest.raises(RouteNotFound):
        run_route_check(deps, COORDS_FROM, COORDS_TO, NIGHT)


def test_place_name_lookup_failure_never_breaks_the_route_check():
    def broken_describe(_lat, _lon):
        raise RuntimeError("reverse geocoding down")

    result = run_route_check(
        _deps(_score_rows(START_CELL, "tinggi", 7.6), describe=broken_describe), COORDS_FROM, COORDS_TO, NIGHT
    )

    assert result.assessment.level == ROUTE_BERISIKO_TINGGI  # status tetap benar
    assert result.assessment.flagged_areas[0].place_name is None  # hanya tanpa nama
