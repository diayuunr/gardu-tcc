"""Tes Fase D: agen Safe Route Advisor (graf LangGraph) — titik, rute, nama ruas, alternatif, narasi, S1-S4."""

import threading
import time
from datetime import datetime

import pytest
from route_helpers import NIGHT, cluster, incident, index_of, point_at, road, route_of

from app.agents.route_agent import (
    ROUTE_AMAN,
    ROUTE_BERISIKO_TINGGI,
    ROUTE_WASPADA,
    PlaceQuery,
    RouteAgentDeps,
    RoutePointError,
    describe_data_coverage,
    generic_center_name,
    run_route_check,
)
from app.agents.risk_agent import WIB, locate_area
from app.core.areas import Area, AreaDirectory
from app.core.config import get_settings
from app.core.directions import RouteNotFound

ORIGIN = PlaceQuery(latitude=point_at(0)[0], longitude=point_at(0)[1])
DESTINATION = PlaceQuery(latitude=point_at(2000)[0], longitude=point_at(2000)[1])
MAIN_ROAD = road("Jalan Kaliurang", 0, 2000, 600)


@pytest.fixture(autouse=True)
def mapbox_configured(monkeypatch):
    """Token palsu supaya titik berupa TEKS lolos pengecekan konfigurasi (geocode di-fake)."""
    monkeypatch.setenv("MAPBOX_TOKEN", "dummy-token-not-real")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _directory():
    lat, lon = point_at(1000, 800)
    return AreaDirectory([
        Area("34.04", "Kabupaten Sleman", "kabkota", None, lat, lon),
        Area("34.04.06", "Depok", "kecamatan", "34.04", lat, lon),  # ~800 m dari rute
        Area("34.04.99", "Terlalu Jauh", "kecamatan", "34.04", *point_at(0, 60_000)),
    ])


def _deps(index=None, *, route=None, directory=None, narrate=None, describe=None, geocode=None, loader=None):
    return RouteAgentDeps(
        supabase=None,
        geocode=geocode or (lambda _text: point_at(0)),
        fetch_route=lambda _o, _d: route or route_of(MAIN_ROAD),
        describe_area=describe or (lambda _a, _b: "Kotagede"),
        narrate=narrate or (lambda _facts: None),
        incident_loader=loader or (lambda _supabase: index or index_of()),
        directory_loader=lambda _supabase: directory,
    )


def _check(deps, **kwargs):
    return run_route_check(deps, ORIGIN, DESTINATION, NIGHT, **kwargs)


# ========================================================== hasil & nama kecamatan


def test_heavy_cluster_makes_the_route_berisiko_tinggi_and_lists_the_named_road_to_avoid():
    result = _check(_deps(index_of(*cluster(10, 1000)), directory=_directory()))

    assessment = result.assessment
    assert assessment.level == ROUTE_BERISIKO_TINGGI and assessment.high_exposure_m >= 200
    [area] = [a for a in assessment.flagged_areas if a.risk_level == "tinggi"]
    assert (area.area_name, area.place_name, area.segment_index) == ("Jalan Kaliurang", "Kec. Depok", 0)
    assert assessment.incident_count == 10 and assessment.areas_with_data == assessment.areas_checked
    assert result.analysis.segments[0].place_name == "Kec. Depok"
    assert result.time_buckets == ("malam",) and result.distance_km == 2.0 and result.duration_minutes == 10
    assert any("Melewati Jalan Kaliurang (Kec. Depok)" in reason for reason in result.analysis.reasons)


def test_segments_get_no_place_name_without_area_data_or_when_no_kecamatan_is_near():
    index = index_of(*cluster(10, 1000))

    no_directory = _check(_deps(index, directory=None))
    assert no_directory.analysis.segments[0].place_name is None
    assert no_directory.assessment.flagged_areas[0].place_name is None  # tetap bernama jalan

    far_only = AreaDirectory([Area("34.04.99", "Terlalu Jauh", "kecamatan", "34.04", *point_at(0, 60_000))])
    assert _check(_deps(index, directory=far_only)).analysis.segments[0].place_name is None  # batas 8 km


def test_route_without_any_incident_data_is_aman_but_reported_as_data_limited():
    result = _check(_deps(index_of(), directory=_directory()))

    assert result.assessment.level == ROUTE_AMAN
    coverage = describe_data_coverage(result.assessment)
    assert (coverage.coverage, coverage.limited) == (0.0, True)
    assert "bukan jaminan aman" in coverage.note
    assert any("Belum ada data kejadian" in r for r in result.analysis.reasons)


def test_partial_coverage_is_reported_and_only_limited_above_the_configured_threshold():
    result = _check(_deps(index_of(incident(1, 0, east_m=1400))))  # dekat awal rute saja, 1,4 km ke timur

    covered, checked = result.assessment.areas_with_data, result.assessment.areas_checked
    assert 0 < covered < checked
    default = describe_data_coverage(result.assessment)
    assert default.limited is False and default.note is None

    strict = describe_data_coverage(
        result.assessment, get_settings().model_copy(update={"route_limited_coverage_threshold": 0.95})
    )
    assert strict.limited is True and f"{covered} dari {checked} titik pemeriksaan" in strict.note


def test_result_is_deterministic_for_identical_input():
    index = index_of(*cluster(6, 700), *cluster(3, 1500, east_m=40, start_ident=20))

    first, second = _check(_deps(index, directory=_directory())), _check(_deps(index, directory=_directory()))

    assert first.analysis == second.analysis and first.assessment == second.assessment


def test_a_verified_cluster_travelled_at_another_hour_does_not_change_the_status():
    index = index_of(*cluster(10, 1000))

    noon = run_route_check(_deps(index), ORIGIN, DESTINATION, datetime(2026, 9, 21, 12, 0, tzinfo=WIB))

    assert noon.assessment.level == ROUTE_AMAN and noon.time_buckets == ("siang",)


# ===================================================================== paralel & error


def test_route_and_incident_index_are_loaded_concurrently():
    loader_started = threading.Event()

    def loader(_supabase):
        loader_started.set()
        return index_of()

    def slow_route(_origin, _destination):
        # Bila indeks dimuat SETELAH rute (berurutan), event tidak pernah terset dan test gagal.
        assert loader_started.wait(timeout=2), "indeks insiden tidak dimuat bersamaan dengan rute"
        return route_of(MAIN_ROAD)

    deps = _deps(loader=loader)
    deps.fetch_route = slow_route

    assert _check(deps).assessment.level == ROUTE_AMAN


def test_point_names_are_fetched_while_the_route_is_being_fetched():
    # Uji nyata: nama titik (reverse geocoding Mapbox, ~2 dtk saat cache dingin) dulu diambil SEBELUM rute.
    # Kedua titik dan rute harus berjalan bersamaan: rute baru boleh selesai bila kedua nama sudah dimintakan.
    barrier = threading.Barrier(3, timeout=2)

    def describe(_lat, _lon):
        barrier.wait()
        return "Nama Titik"

    def slow_route(_origin, _destination):
        barrier.wait()
        return route_of(MAIN_ROAD)

    deps = _deps(describe=describe)
    deps.fetch_route = slow_route

    result = _check(deps)

    assert result.origin_name == "Nama Titik" and result.destination_name == "Nama Titik"


def test_both_text_points_are_geocoded_at_the_same_time():
    barrier = threading.Barrier(2, timeout=2)

    def geocode(_text):
        barrier.wait()  # hanya lewat bila KEDUA titik di-geocode bersamaan
        return point_at(0)

    result = run_route_check(_deps(geocode=geocode), PlaceQuery(text="asal"), PlaceQuery(text="tujuan"), NIGHT)

    assert result.origin == point_at(0)


def test_invalid_points_raise_clear_errors_and_route_failures_propagate():
    with pytest.raises(RoutePointError, match="asal.*luar wilayah Yogyakarta"):
        run_route_check(_deps(), PlaceQuery(latitude=-6.2, longitude=106.8), DESTINATION, NIGHT)  # Jakarta
    with pytest.raises(RoutePointError, match="tujuan tidak ditemukan"):
        run_route_check(_deps(geocode=lambda _t: None), ORIGIN, PlaceQuery(text="tempat ngawur"), NIGHT)
    with pytest.raises(RoutePointError, match="belum diisi"):
        run_route_check(_deps(), PlaceQuery(), DESTINATION, NIGHT)

    def no_route(_o, _d):
        raise RouteNotFound("tidak ada rute")

    deps = _deps()
    deps.fetch_route = no_route
    with pytest.raises(RouteNotFound):
        _check(deps)


def test_incident_load_failure_propagates_so_the_api_can_answer_502():
    def broken(_supabase):
        raise RuntimeError("database down")

    with pytest.raises(RuntimeError):
        _check(_deps(loader=broken))


# ====================================================================== narasi (D8)


def test_narrative_only_requested_and_only_for_non_safe_routes_with_road_names_and_no_coordinates():
    seen = []

    def narrate(facts):
        seen.append(facts)
        return "Rute melewati ruas yang perlu diwaspadai."

    risky = index_of(*cluster(10, 1000, category="penyerangan"))

    default = _check(_deps(risky, directory=_directory(), narrate=narrate))
    assert default.narrative is None and seen == []

    asked = _check(_deps(risky, directory=_directory(), narrate=narrate), include_narrative=True)
    assert asked.narrative == "Rute melewati ruas yang perlu diwaspadai."
    facts = seen[0]
    assert facts.route_level == ROUTE_BERISIKO_TINGGI
    assert facts.avoid_places == ("Jalan Kaliurang (Kec. Depok)",)
    assert facts.areas_checked == asked.assessment.areas_checked
    assert "-7." not in repr(facts) and "110." not in repr(facts)  # tanpa koordinat

    safe = _check(_deps(index_of(), narrate=narrate), include_narrative=True)
    assert safe.narrative is None and len(seen) == 1


# ================================================================ alternatif (D6/D10)


def _with_alternatives(main_cluster=True, alt_duration=660.0, alt_east=1000.0, **index_extra):
    alt = route_of(road("Jalan Alternatif", 0, 2000, alt_duration, east_m=alt_east))
    route = route_of(MAIN_ROAD, alternatives=[alt])
    incidents = [*cluster(10, 1000), *index_extra.get("extra", [])] if main_cluster else list(index_extra.get("extra", []))
    return route, index_of(*incidents)


def test_a_clearly_safer_alternative_with_comparable_data_is_recommended_with_extra_time():
    route, index = _with_alternatives(extra=[incident(100, 700, east_m=1000)])  # data tersedia di sekitar alternatif

    result = _check(_deps(index, route=route, directory=_directory()))

    assert result.assessment.level == ROUTE_BERISIKO_TINGGI
    [alt] = result.alternatives
    assert alt.is_lowest_risk is True and alt.assessment.level == ROUTE_AMAN
    assert alt.extra_minutes == 1 and alt.duration_minutes == 11  # 660 dtk vs 600 dtk
    assert any("Lebih rendah risikonya dibanding rute utama, sekitar 1 menit lebih lama" in r for r in alt.analysis.reasons)
    assert any("Tersedia rute alternatif dengan risiko lebih rendah" in r for r in result.analysis.reasons)
    assert alt.analysis.segments[0].road_name == "Jalan Alternatif"


def test_alternative_that_only_looks_safe_because_it_has_no_data_is_not_recommended():
    route, index = _with_alternatives(alt_east=6000)  # >1,5 km dari semua insiden: tanpa data sama sekali

    [alt] = _check(_deps(index, route=route)).alternatives

    assert alt.assessment.level == ROUTE_AMAN and alt.assessment.areas_with_data == 0
    assert alt.is_lowest_risk is False  # "aman" di sini hanya berarti "belum ada data"
    assert alt.extra_minutes == 1


def test_alternative_much_slower_than_the_main_route_is_not_recommended():
    route, index = _with_alternatives(alt_duration=1200.0, extra=[incident(100, 700, east_m=1000)])  # +100%

    [alt] = _check(_deps(index, route=route)).alternatives

    assert alt.assessment.level == ROUTE_AMAN and alt.is_lowest_risk is False and alt.extra_minutes == 10


def test_when_the_main_route_is_already_the_lowest_risk_no_alternative_is_marked():
    worse = route_of(road("Jalan Alternatif", 0, 2000, 600, east_m=0.0))  # alternatif melewati kluster yang sama
    route = route_of(road("Jalan Utama", 0, 2000, 600, east_m=1000), alternatives=[worse])

    result = _check(_deps(index_of(*cluster(10, 1000), incident(100, 700, east_m=1000)), route=route))

    assert result.assessment.level == ROUTE_AMAN
    assert [a.is_lowest_risk for a in result.alternatives] == [False]
    assert result.alternatives[0].assessment.level == ROUTE_BERISIKO_TINGGI


def test_at_most_the_configured_number_of_alternatives_is_assessed(monkeypatch):
    monkeypatch.setenv("ROUTE_MAX_ALTERNATIVES", "1")
    get_settings.cache_clear()
    alts = [route_of(road(f"Alt {i}", 0, 2000, 600, east_m=1000 + 100 * i)) for i in range(3)]

    result = _check(_deps(index_of(*cluster(10, 1000)), route=route_of(MAIN_ROAD, alternatives=alts)))

    assert len(result.alternatives) == 1


# ================================================ S4: nama titik & catatan geocoding


def test_point_names_are_always_filled_even_when_reverse_geocoding_is_unavailable():
    def no_name(_lat, _lon):
        return None

    from_text = run_route_check(_deps(describe=no_name), PlaceQuery(text="Gedongkuning"), DESTINATION, NIGHT)
    assert from_text.origin_name == "Gedongkuning"  # teks yang diketik pengguna sendiri
    assert from_text.destination_name == locate_area(*point_at(2000), 0.01)[2]  # koordinat/GPS: label sel netral

    def broken(_lat, _lon):
        raise RuntimeError("reverse geocoding down")

    result = _check(_deps(describe=broken))
    assert result.origin_name and result.destination_name


def test_gps_points_fall_back_to_the_kecamatan_name_from_our_own_data_before_the_grid_label():
    directory = _directory()  # kecamatan Depok ~800 m dari titik rute

    result = run_route_check(
        _deps(directory=directory, describe=lambda _a, _b: None), ORIGIN, DESTINATION, NIGHT
    )

    assert (result.origin_name, result.destination_name) == ("Kec. Depok", "Kec. Depok")


def test_reverse_geocoded_name_wins_over_the_fallbacks():
    result = run_route_check(_deps(), PlaceQuery(text="Gedongkuning"), DESTINATION, NIGHT)

    assert (result.origin_name, result.destination_name) == ("Kotagede", "Kotagede")


CITY_CENTER = (-7.7956, 110.3695)


def test_text_geocoded_to_a_city_centre_gets_a_cautionary_note_without_echoing_the_text():
    near_center = (CITY_CENTER[0] + 0.0005, CITY_CENTER[1] - 0.0005)  # ~80 m dari pusat

    result = run_route_check(
        _deps(geocode=lambda _t: near_center), PlaceQuery(text="rumah pak RAHASIA-ALAMAT"), DESTINATION, NIGHT
    )

    [note] = result.location_notes
    assert "asal" in note and "pusat Kota Yogyakarta" in note and "GPS" in note
    assert "RAHASIA-ALAMAT" not in note


def test_specific_text_result_and_coordinates_get_no_note_even_at_the_city_centre():
    assert run_route_check(_deps(), PlaceQuery(text="Gedongkuning"), DESTINATION, NIGHT).location_notes == ()
    gps = run_route_check(_deps(), PlaceQuery(latitude=CITY_CENTER[0], longitude=CITY_CENTER[1]), DESTINATION, NIGHT)
    assert gps.location_notes == ()  # koordinat dari pengguna, bukan tebakan geocoder


def test_generic_center_detection_respects_the_radius():
    assert generic_center_name((CITY_CENTER[0] + 0.001, CITY_CENTER[1]), 500) == "Kota Yogyakarta"  # ~110 m
    assert generic_center_name((CITY_CENTER[0] + 0.01, CITY_CENTER[1]), 500) is None  # ~1,1 km
    assert generic_center_name(point_at(0), 500) is None


# ======================================================================= performa (D9)


def test_full_check_with_1000_incidents_and_three_routes_stays_well_under_the_time_budget():
    incidents = [incident(i, (i * 53) % 9000, (i % 9 - 4) * 70) for i in range(1000)]
    long_main = route_of(road("Jalan Panjang", 0, 9000, 1200, points=40))
    route = route_of(
        road("Jalan Panjang", 0, 9000, 1200, points=40),
        alternatives=[long_main, route_of(road("Alt", 0, 9000, 1300, points=40, east_m=500))],
    )

    started = time.perf_counter()
    result = run_route_check(_deps(index_of(*incidents), route=route, directory=_directory()), ORIGIN, DESTINATION, NIGHT)
    elapsed = time.perf_counter() - started

    print(f"cek rute 3 rute x {result.assessment.areas_checked} titik x 1000 insiden: {elapsed * 1000:.0f} ms")
    assert elapsed < 3.0 and result.assessment.areas_checked > 60
