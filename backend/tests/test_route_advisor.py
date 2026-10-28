"""Tes Tahap 3 Safe Route Advisor: S1 cakupan data, S2 aturan status berbasis paparan,
S3 rute alternatif, S4 nama titik & catatan geocoding."""

import itertools
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.risk_agent import WIB, locate_area
from app.agents.route_agent import (
    ROUTE_AMAN,
    ROUTE_BERISIKO_TINGGI,
    ROUTE_WASPADA,
    CrossedCell,
    PlaceQuery,
    RouteAgentDeps,
    StoredScore,
    assess_route,
    build_alternatives,
    crossed_cells,
    describe_data_coverage,
    generic_center_name,
    haversine_meters,
    run_route_check,
    sample_route,
)
from app.api.route import get_route_agent_deps
from app.core.config import get_settings
from app.core.directions import RouteGeometry, fetch_route
from app.main import app

client = TestClient(app)

GEDONGKUNING = (-7.812995, 110.39872)
TUGU = (-7.7830, 110.3670)
CITY_CENTER = (-7.7956, 110.3695)
NIGHT = datetime(2026, 9, 20, 22, 0, tzinfo=WIB)
ALL_BUCKETS = ("dini_hari", "pagi", "siang", "sore", "malam")
FROM = PlaceQuery(latitude=GEDONGKUNING[0], longitude=GEDONGKUNING[1])
TO = PlaceQuery(latitude=TUGU[0], longitude=TUGU[1])


@pytest.fixture(autouse=True)
def mapbox_configured(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "dummy-token-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _route(*waypoints, duration_s=1260.0, alternatives=()) -> RouteGeometry:
    points = (GEDONGKUNING, *waypoints, TUGU)
    distance = sum(haversine_meters(a, b) for a, b in itertools.pairwise(points))
    return RouteGeometry(points=points, distance_m=distance, duration_s=duration_s, alternatives=tuple(alternatives))


MAIN = _route(((GEDONGKUNING[0] + TUGU[0]) / 2, (GEDONGKUNING[1] + TUGU[1]) / 2))
ALT_SOUTH = _route((-7.830, 110.370), duration_s=1500.0)
ALT_WEST = _route((-7.820, 110.360), duration_s=1380.0)


def _cells_of(route: RouteGeometry) -> list[str]:
    crossed = crossed_cells(sample_route(route.points, 250, 400), NIGHT, route.duration_s, get_settings())
    return [cell.area_name for cell in crossed]


def _rows(area_names, level, score):
    return [
        {"area_name": area, "time_bucket": bucket, "risk_score": score, "risk_level": level}
        for area in area_names
        for bucket in ALL_BUCKETS
    ]


class _Supabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "risk_scores"
        return _Query(self.rows)


class _Query:
    def __init__(self, rows):
        self._rows, self._filters = rows, []

    def select(self, _columns):
        return self

    def in_(self, column, values):
        self._filters.append((column, set(values)))
        return self

    def execute(self):
        return SimpleNamespace(data=[r for r in self._rows if all(r[c] in v for c, v in self._filters)])


def _deps(rows, *, route=MAIN, describe=lambda _lat, _lon: "Kotagede", geocode=None) -> RouteAgentDeps:
    return RouteAgentDeps(
        supabase=_Supabase(rows),
        geocode=geocode or (lambda _text: GEDONGKUNING),
        fetch_route=lambda _o, _d: route,
        describe_area=describe,
        narrate=lambda _facts: None,
    )


def _check(rows, **kwargs):
    return run_route_check(_deps(rows, **kwargs), FROM, TO, NIGHT)


# ====================================================================== S1: cakupan data


def test_route_without_any_data_stays_aman_but_is_flagged_as_data_limited_with_a_note():
    result = _check([])

    assert result.assessment.level == ROUTE_AMAN  # kompatibel dengan SRS
    coverage = describe_data_coverage(result.assessment)
    assert coverage.coverage == 0.0 and coverage.limited is True
    assert "belum ada data" in coverage.note.lower() and "bukan jaminan aman" in coverage.note


def test_partial_coverage_is_reported_and_only_limited_above_the_configured_threshold():
    cells = _cells_of(MAIN)
    result = _check(_rows(cells[:2], "rendah", 1.0))
    expected = round(2 / len(cells), 3)

    default = describe_data_coverage(result.assessment)
    assert default.coverage == expected and default.limited is False and default.note is None

    strict = describe_data_coverage(
        result.assessment, get_settings().model_copy(update={"route_limited_coverage_threshold": 0.9})
    )
    assert strict.limited is True and f"2 dari {len(cells)} area" in strict.note


def test_api_exposes_coverage_fields_for_a_route_without_data():
    app.dependency_overrides[get_route_agent_deps] = lambda: _deps([])
    try:
        body = client.post(
            "/route/check",
            json={"origin": {"latitude": GEDONGKUNING[0], "longitude": GEDONGKUNING[1]},
                  "destination": {"latitude": TUGU[0], "longitude": TUGU[1]}},
        ).json()
    finally:
        app.dependency_overrides.pop(get_route_agent_deps, None)

    assert body["risk_level"] == "aman"
    assert (body["data_coverage"], body["data_limited"]) == (0.0, True)
    assert "bukan jaminan aman" in body["data_note"]


# ================================================================= S2: aturan status paparan


def _scenario(*levels_and_scores, settings=None):
    """Penilaian untuk rute yang melintasi sel-sel buatan dengan (level, skor) yang diberikan."""
    cells = [CrossedCell(f"Area {i}", -7.8, 110.3, "malam", i / 10) for i in range(len(levels_and_scores))]
    scores = {(c.area_name, "malam"): StoredScore(score, level) for c, (level, score) in zip(cells, levels_and_scores)}
    return assess_route(cells, scores, settings or get_settings())


@pytest.mark.parametrize(
    ("cells", "expected"),
    [
        ([("rendah", 1.0)], ROUTE_AMAN),
        ([("sedang", 4.0)], ROUTE_AMAN),  # satu sel sedang tunggal tidak cukup (kode lama: waspada)
        ([("sedang", 4.0), ("sedang", 5.0)], ROUTE_WASPADA),
        ([("sedang", 4.0), ("rendah", 1.0), ("sedang", 3.5)], ROUTE_WASPADA),
        ([("tinggi", 7.2)], ROUTE_BERISIKO_TINGGI),
        ([("tinggi", 7.2), ("sedang", 4.0)], ROUTE_BERISIKO_TINGGI),
    ],
)
def test_default_exposure_rule(cells, expected):
    assert _scenario(*cells).level == expected


def test_single_medium_cell_is_still_listed_for_the_user_to_watch():
    assessment = _scenario(("sedang", 4.0))

    assert assessment.level == ROUTE_AMAN
    assert [a.risk_level for a in assessment.flagged_areas] == ["sedang"]


def test_one_high_cell_below_the_required_count_is_waspada_unless_its_score_is_critical():
    strict = get_settings().model_copy(update={"route_min_high_cells": 2})

    assert _scenario(("tinggi", 7.5), settings=strict).level == ROUTE_WASPADA
    assert _scenario(("tinggi", 8.6), settings=strict).level == ROUTE_BERISIKO_TINGGI  # skor kritis >= 8.5
    assert _scenario(("tinggi", 7.5), ("tinggi", 7.1), settings=strict).level == ROUTE_BERISIKO_TINGGI


@pytest.mark.parametrize(("min_high", "min_medium"), list(itertools.product((1, 2, 3), (1, 2, 5))))
def test_a_route_crossing_a_high_score_area_is_never_shown_as_aman_for_any_configuration(min_high, min_medium):
    """TC-RTE-001 sebagai invarian."""
    settings = get_settings().model_copy(
        update={"route_min_high_cells": min_high, "route_min_medium_cells": min_medium}
    )

    for score in (7.0, 7.9, 9.5):
        assert _scenario(("tinggi", score), settings=settings).level != ROUTE_AMAN


def test_status_counts_all_cells_even_though_the_listed_areas_are_capped():
    assessment = _scenario(*[("sedang", 4.0 + i / 100) for i in range(8)])

    assert assessment.level == ROUTE_WASPADA
    assert len(assessment.flagged_areas) == 5  # daftar tampilan dipotong, status tidak terpengaruh


def test_exposure_rule_end_to_end_on_a_real_route():
    cells = _cells_of(MAIN)

    one_medium = _check(_rows(cells[:1], "sedang", 4.0)).assessment
    two_medium = _check(_rows(cells[:2], "sedang", 4.0)).assessment
    one_high = _check(_rows(cells[:1], "tinggi", 7.6)).assessment

    assert (one_medium.level, two_medium.level, one_high.level) == (ROUTE_AMAN, ROUTE_WASPADA, ROUTE_BERISIKO_TINGGI)


# =================================================================== S3: rute alternatif


def _scenario_with_alternatives(*, main_high=True, alt_south=("rendah", 1.0), alt_west=None):
    """Rute utama melintasi sel tinggi yang HANYA ada di rute utama; skor alternatif disetel."""
    main_cells, south_cells, west_cells = _cells_of(MAIN), _cells_of(ALT_SOUTH), _cells_of(ALT_WEST)
    main_only = [c for c in main_cells if c not in south_cells and c not in west_cells]
    assert main_only, "geometri uji harus punya sel yang eksklusif di rute utama"
    rows = _rows(main_only[:1], "tinggi", 7.8) if main_high else _rows(main_only[:1], "rendah", 1.0)
    if alt_south:
        rows += _rows([c for c in south_cells if c not in main_cells] or south_cells, alt_south[0], alt_south[1])
    if alt_west:
        rows += _rows([c for c in west_cells if c not in main_cells] or west_cells, alt_west[0], alt_west[1])
    alternatives = [ALT_SOUTH] + ([ALT_WEST] if alt_west is not None else [])
    route = _route(((GEDONGKUNING[0] + TUGU[0]) / 2, (GEDONGKUNING[1] + TUGU[1]) / 2), alternatives=alternatives)
    return _check(rows, route=route)


def test_clearly_safer_alternative_is_marked_lowest_risk_and_summarised():
    result = _scenario_with_alternatives()

    assert result.assessment.level == ROUTE_BERISIKO_TINGGI
    [alternative] = result.alternatives
    assert alternative.is_lowest_risk is True
    assert alternative.assessment.level == ROUTE_AMAN and alternative.assessment.max_risk_score == 1.0
    assert alternative.duration_minutes == 25 and alternative.distance_km > 0


def test_alternative_that_is_not_clearly_lower_is_never_recommended():
    same = _scenario_with_alternatives(alt_south=("tinggi", 7.9))  # sama-sama tinggi, selisih skor 0.1 < 0.5
    assert [a.is_lowest_risk for a in same.alternatives] == [False]

    worse = _scenario_with_alternatives(main_high=False, alt_south=("tinggi", 9.0))
    assert [a.is_lowest_risk for a in worse.alternatives] == [False]


def test_same_level_alternative_needs_a_score_gain_of_at_least_the_configured_minimum():
    main = _scenario(("tinggi", 8.0)); main_assessment = main
    small = _scenario(("tinggi", 7.8))
    large = _scenario(("tinggi", 7.4))

    marked = build_alternatives(main_assessment, [(small, 5.0, 20), (large, 5.0, 22)])

    assert [a.is_lowest_risk for a in marked] == [False, True]  # gain 0.2 ditolak, 0.6 diterima


def test_alternative_with_no_data_at_all_is_not_recommended_even_though_its_score_is_zero():
    result = _scenario_with_alternatives(alt_south=None)

    assert result.assessment.level == ROUTE_BERISIKO_TINGGI
    assert [a.is_lowest_risk for a in result.alternatives] == [False]
    assert result.alternatives[0].assessment.areas_with_data == 0


def test_only_one_alternative_is_marked_the_best_by_level_then_score_then_speed():
    result = _scenario_with_alternatives(alt_south=("rendah", 2.0), alt_west=("rendah", 1.0))

    flags = {a.duration_minutes: a.is_lowest_risk for a in result.alternatives}
    assert flags == {25: False, 23: True}  # barat (23 mnt) skor 1.0 < selatan (25 mnt) skor 2.0


def test_at_most_the_configured_number_of_alternatives_are_assessed(monkeypatch):
    monkeypatch.setenv("ROUTE_MAX_ALTERNATIVES", "1")
    get_settings.cache_clear()

    result = _scenario_with_alternatives(alt_west=("rendah", 1.0))

    assert len(result.alternatives) == 1


def test_alternatives_add_no_reverse_geocoding_calls_beyond_the_main_route():
    calls = []

    def describe(lat, lon):
        calls.append((lat, lon))
        return "Kotagede"

    cells = _cells_of(MAIN)
    route = _route(((GEDONGKUNING[0] + TUGU[0]) / 2, (GEDONGKUNING[1] + TUGU[1]) / 2), alternatives=[ALT_SOUTH, ALT_WEST])
    rows = _rows(cells[:1], "tinggi", 7.8) + _rows(_cells_of(ALT_SOUTH), "tinggi", 7.8) + _rows(_cells_of(ALT_WEST), "tinggi", 7.8)

    run_route_check(_deps(rows, route=route, describe=describe), FROM, TO, NIGHT)

    # 2 titik asal/tujuan + area berisiko rute utama; alternatif tidak diberi nama.
    assert len(calls) <= 2 + 5


def test_api_returns_alternative_summaries_and_the_safer_flag():
    main_only = [c for c in _cells_of(MAIN) if c not in _cells_of(ALT_SOUTH)]
    rows = _rows(main_only[:1], "tinggi", 7.8) + _rows(_cells_of(ALT_SOUTH), "rendah", 1.0)
    route = _route(((GEDONGKUNING[0] + TUGU[0]) / 2, (GEDONGKUNING[1] + TUGU[1]) / 2), alternatives=[ALT_SOUTH])
    departure = (datetime.now(WIB) + timedelta(hours=1)).replace(tzinfo=None, microsecond=0)  # dalam jendela validasi API

    app.dependency_overrides[get_route_agent_deps] = lambda: _deps(rows, route=route)
    try:
        response = client.post(
            "/route/check",
            json={"origin": {"latitude": GEDONGKUNING[0], "longitude": GEDONGKUNING[1]},
                  "destination": {"latitude": TUGU[0], "longitude": TUGU[1]},
                  "departure_time": departure.isoformat()},
        )
    finally:
        app.dependency_overrides.pop(get_route_agent_deps, None)

    assert response.status_code == 200
    body = response.json()
    assert body["safer_alternative_available"] is True
    [alternative] = body["alternatives"]
    assert set(alternative) == {
        "risk_level", "max_risk_score", "distance_km", "duration_minutes",
        "data_coverage", "data_limited", "is_lowest_risk",
    }
    assert alternative["is_lowest_risk"] is True and alternative["risk_level"] == "aman"


# --- parsing alternatif Mapbox (satu panggilan, alternatives=true)


def _mapbox_route(offset=0.0, duration=1000.0):
    return {
        "geometry": {"coordinates": [[110.39872 + offset, -7.812995], [110.38 + offset, -7.80], [110.367, -7.783]]},
        "distance": 4800.0,
        "duration": duration,
    }


class _MapboxResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _stub_mapbox(monkeypatch, routes):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return _MapboxResponse({"code": "Ok", "routes": routes})

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_directions_requests_alternatives_in_the_same_call_and_parses_at_most_two(monkeypatch):
    calls = _stub_mapbox(monkeypatch, [_mapbox_route(), _mapbox_route(0.01, 1100), _mapbox_route(0.02, 1200), _mapbox_route(0.03, 1300)])

    route = fetch_route(GEDONGKUNING, TUGU)

    assert len(calls) == 1 and calls[0]["alternatives"] == "true"
    assert [a.duration_s for a in route.alternatives] == [1100.0, 1200.0]  # maks 2; yang ketiga dibuang
    assert route.alternatives[0].alternatives == ()  # tidak bersarang


def test_directions_skips_a_malformed_alternative_but_keeps_the_main_route(monkeypatch):
    _stub_mapbox(monkeypatch, [_mapbox_route(), {"geometry": {"coordinates": [[110.3, -7.8]]}, "distance": 1, "duration": 1}])

    route = fetch_route(GEDONGKUNING, TUGU)

    assert route.duration_s == 1000.0 and route.alternatives == ()


def test_directions_asks_for_no_alternatives_when_disabled(monkeypatch):
    monkeypatch.setenv("ROUTE_MAX_ALTERNATIVES", "0")
    get_settings.cache_clear()
    calls = _stub_mapbox(monkeypatch, [_mapbox_route(), _mapbox_route(0.01)])

    route = fetch_route(GEDONGKUNING, TUGU)

    assert calls[0]["alternatives"] == "false" and route.alternatives == ()


# ======================================================= S4: nama titik & catatan geocoding


def test_point_names_are_always_filled_even_when_reverse_geocoding_is_unavailable():
    def no_name(_lat, _lon):
        return None

    from_text = run_route_check(
        _deps([], describe=no_name, geocode=lambda _t: GEDONGKUNING), PlaceQuery(text="Gedongkuning"), TO, NIGHT
    )
    assert from_text.origin_name == "Gedongkuning"  # teks yang diketik pengguna sendiri
    assert from_text.destination_name == locate_area(*TUGU, 0.01)[2]  # koordinat/GPS: label sel netral

    def broken(_lat, _lon):
        raise RuntimeError("reverse geocoding down")

    result = run_route_check(_deps([], describe=broken), FROM, TO, NIGHT)
    assert result.origin_name and result.destination_name


def test_reverse_geocoded_name_wins_over_the_fallbacks():
    result = run_route_check(_deps([]), PlaceQuery(text="Gedongkuning"), TO, NIGHT)

    assert (result.origin_name, result.destination_name) == ("Kotagede", "Kotagede")


def test_text_geocoded_to_a_city_centre_gets_a_cautionary_note_without_echoing_the_text():
    near_center = (CITY_CENTER[0] + 0.0005, CITY_CENTER[1] - 0.0005)  # ~80 m dari pusat
    result = run_route_check(
        _deps([], geocode=lambda _t: near_center), PlaceQuery(text="rumah pak RAHASIA-ALAMAT"), TO, NIGHT
    )

    [note] = result.location_notes
    assert "asal" in note and "pusat Kota Yogyakarta" in note and "GPS" in note
    assert "RAHASIA-ALAMAT" not in note


def test_specific_text_result_and_coordinates_get_no_note_even_at_the_city_centre():
    specific = run_route_check(_deps([]), PlaceQuery(text="Gedongkuning"), TO, NIGHT)
    assert specific.location_notes == ()

    gps_at_center = run_route_check(
        _deps([]), PlaceQuery(latitude=CITY_CENTER[0], longitude=CITY_CENTER[1]), TO, NIGHT
    )
    assert gps_at_center.location_notes == ()  # koordinat dari pengguna, bukan hasil tebakan geocoder


def test_destination_note_is_reported_separately_from_origin():
    near_bantul = (-7.8883, 110.3287)
    result = run_route_check(
        _deps([], geocode=lambda _t: near_bantul), FROM, PlaceQuery(text="Bantul"), NIGHT
    )

    [note] = result.location_notes
    assert "tujuan" in note and "pusat Kabupaten Bantul" in note


def test_generic_center_detection_respects_the_radius():
    assert generic_center_name((CITY_CENTER[0] + 0.001, CITY_CENTER[1]), 500) == "Kota Yogyakarta"  # ~110 m
    assert generic_center_name((CITY_CENTER[0] + 0.01, CITY_CENTER[1]), 500) is None  # ~1,1 km
    assert generic_center_name(GEDONGKUNING, 500) is None


def test_api_returns_location_notes_and_filled_point_names():
    near_center = (CITY_CENTER[0] + 0.0004, CITY_CENTER[1])
    app.dependency_overrides[get_route_agent_deps] = lambda: _deps(
        [], describe=lambda _a, _b: None, geocode=lambda _t: near_center
    )
    try:
        body = client.post(
            "/route/check",
            json={"origin": {"text": "tempat ngawur"},
                  "destination": {"latitude": TUGU[0], "longitude": TUGU[1]}},
        ).json()
    finally:
        app.dependency_overrides.pop(get_route_agent_deps, None)

    assert len(body["location_notes"]) == 1
    assert body["origin"]["place_name"] == "tempat ngawur"
    assert body["destination"]["place_name"].startswith("Area ")
