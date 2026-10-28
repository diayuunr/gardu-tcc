"""Tes Fase D (D3-D7, D9, D10): analisis rute berbasis kedekatan insiden — fungsi murni."""

import re
import time
from datetime import datetime, timedelta

import pytest
from route_helpers import BASE_LAT, BASE_LON, NIGHT, RECENT, cluster, incident, index_of, point_at, road, route_of

from app.agents.incident_index import IncidentIndex, IndexedIncident
from app.agents.risk_agent import WIB, time_bucket_of
from app.agents.route_analysis import (
    ROUTE_AMAN,
    ROUTE_BERISIKO_TINGGI,
    ROUTE_WASPADA,
    CheckPoint,
    RouteAnalysis,
    _effective_steps,
    analyze_route,
    bucket_weight,
    build_check_points,
    build_reasons,
    decide_status,
    distance_weight,
    pick_safer_alternative,
    sample_route,
    score_point,
    simplify_polyline,
)
from app.core.config import get_settings
from app.core.geo import haversine_meters

SETTINGS = get_settings()
ONE_STEP = road("Jalan Kaliurang", 0, 2000, 600)  # 2 km, 10 menit, malam


def _analyze(index, *steps, departure=NIGHT, settings=SETTINGS):
    return analyze_route(route_of(*(steps or (ONE_STEP,))), departure, index, settings)


# ============================================================================ bobot


def test_time_buckets_weight_full_when_equal_partial_when_adjacent_and_zero_otherwise():
    assert bucket_weight("malam", "malam", 0.5) == 1.0
    assert bucket_weight("malam", "sore", 0.5) == bucket_weight("sore", "malam", 0.5) == 0.5
    assert bucket_weight("malam", "dini_hari", 0.5) == 0.5  # siklus 24 jam: 23.00 dan 01.00 bertetangga
    assert bucket_weight("pagi", "siang", 0.3) == 0.3
    assert bucket_weight("malam", "siang", 0.5) == 0.0
    assert bucket_weight("dini_hari", "sore", 0.5) == 0.0


def test_distance_kernels_decay_to_zero_at_the_radius():
    assert distance_weight(0, 300, "linear") == 1.0
    assert distance_weight(150, 300, "linear") == pytest.approx(0.5)
    assert distance_weight(300, 300, "linear") == 0.0 and distance_weight(500, 300, "gaussian") == 0.0
    gaussian = [distance_weight(d, 300, "gaussian") for d in (0, 75, 150, 225, 299)]
    assert gaussian[0] == 1.0 and gaussian == sorted(gaussian, reverse=True) and gaussian[-1] < 0.05


def test_incident_weight_scales_with_distance_recency_and_hour_match():
    def point_score(**kwargs):
        a = _analyze(index_of(incident(1, 1000, **kwargs)))
        return max(s.max_score for s in a.segments)

    on_route, at_150m, beyond_radius = point_score(), point_score(east_m=150), point_score(east_m=400)
    assert on_route > at_150m > beyond_radius == 0.0  # makin dekat makin berat; di luar 300 m tidak dihitung

    old = point_score(when=RECENT.replace(year=2021))  # ~5 tahun lalu: bobot ~separuh
    assert 0 < old < on_route

    other_hour = point_score(when=RECENT.replace(hour=13))  # siang vs perjalanan malam: tidak bersebelahan -> diabaikan
    adjacent_hour = point_score(when=RECENT.replace(hour=17))  # sore vs malam: bertetangga -> bobot sebagian
    assert other_hour == 0.0 and 0 < adjacent_hour < on_route


def test_a_single_incident_on_the_route_is_rendah_like_the_heatmap_calibration():
    analysis = _analyze(index_of(incident(1, 1000)))

    [segment] = analysis.segments
    assert segment.max_score == pytest.approx(2.82, abs=0.02)  # satu insiden berbobot ~1 = 2.83 (sama dengan heatmap)
    assert segment.level == "rendah" and analysis.status == ROUTE_AMAN
    assert segment.incident_count == 1


def test_incident_outside_the_radius_still_counts_as_nearby_data_but_not_as_a_contributor():
    analysis = _analyze(index_of(incident(1, 1000, east_m=400)))

    [segment] = analysis.segments
    assert segment.incident_count == 0 and segment.max_score == 0.0
    assert segment.has_nearby_data is True  # ada data di sekitar (<1,5 km): "tidak ada kejadian dekat", bukan "tanpa data"
    assert analysis.data_coverage == 1.0


def test_no_incidents_anywhere_means_no_coverage():
    analysis = _analyze(index_of())

    assert (analysis.covered_points, analysis.data_coverage, analysis.status) == (0, 0.0, ROUTE_AMAN)
    assert analysis.segments[0].has_nearby_data is False


# =================================================== waktu & musim PER TITIK (D7)


def test_arrival_time_bucket_and_date_are_computed_per_point_across_hour_and_midnight_boundaries():
    route = route_of(road("Jalan Kaliurang", 0, 2000, 1200))  # 20 menit
    steps = _effective_steps(route)

    evening = build_check_points(steps, datetime(2026, 9, 20, 17, 50, tzinfo=WIB), SETTINGS)
    assert evening[0].bucket == "sore" and evening[-1].bucket == "malam"  # pergantian jam 18.00 di tengah rute
    assert [p.bucket for p in evening] == sorted((p.bucket for p in evening), key=["sore", "malam"].index)

    midnight = build_check_points(steps, datetime(2027, 1, 24, 23, 50, tzinfo=WIB), SETTINGS)
    assert midnight[0].arrival.date() < midnight[-1].arrival.date()  # lewat tengah malam
    assert midnight[0].bucket == "malam" and midnight[-1].bucket == "dini_hari"


def test_seasonal_multiplier_follows_each_points_own_arrival_date_not_the_departure_date():
    """Berangkat 23.50 lalu melewati tengah malam: titik yang tiba setelah 00.00 jatuh pada TANGGAL BERIKUTNYA,
    dan jendela 'jelang Ramadan' (mulai 25 Jan 2027) hanya berlaku untuk titik-titik itu."""
    spot = incident(1, 0, when=datetime(2027, 1, 20, 1, 0, tzinfo=WIB))  # kejadian dini hari
    index = index_of(spot)
    lat, lon = point_at(0)

    def score(arrival: datetime, departure: datetime):
        point = CheckPoint(lat, lon, 0.0, arrival, time_bucket_of(arrival), 0)
        return score_point(point, index, departure, SETTINGS)

    departure = datetime(2027, 1, 24, 23, 50, tzinfo=WIB)  # tanggal berangkat: 24 Jan (di luar jendela)
    before_midnight = score(datetime(2027, 1, 24, 23, 55, tzinfo=WIB), departure)
    after_midnight = score(datetime(2027, 1, 25, 0, 20, tzinfo=WIB), departure)  # tanggal tiba: 25 Jan

    assert before_midnight.season is None
    assert after_midnight.season == "jelang_ramadan"  # memakai tanggal tiba, bukan tanggal berangkat
    # Dini hari (00.20) vs malam (23.55): bucket berbeda, jadi bandingkan terhadap titik dini hari di tanggal 24:
    earlier_day = score(datetime(2027, 1, 24, 0, 20, tzinfo=WIB), datetime(2027, 1, 23, 23, 50, tzinfo=WIB))
    assert earlier_day.season is None
    assert after_midnight.score == pytest.approx(earlier_day.score * SETTINGS.risk_ramadan_multiplier, rel=0.03)


def test_season_is_reported_in_the_analysis_and_reasons_when_the_trip_falls_inside_ramadan():
    spot = cluster(3, 1000, when=datetime(2027, 2, 1, 22, 0, tzinfo=WIB))
    analysis = _analyze(index_of(*spot), departure=datetime(2027, 2, 20, 22, 0, tzinfo=WIB))

    assert analysis.seasons == ("selama_ramadan",)
    assert any("selama Ramadan" in reason for reason in build_reasons(analysis, SETTINGS, False))


# ===================================================================== segmentasi (D4)


def _segmented_route():
    return (
        road("Jalan A", 0, 1000, 300),
        road("jalan a", 1000, 2000, 300),  # nama sama (beda huruf besar) berurutan -> digabung
        road("Jalan B", 2000, 3000, 300),
        road("", 3000, 3500, 150),  # tanpa nama
        road("", 3500, 4000, 150),
    )


def test_consecutive_steps_with_the_same_name_merge_and_unnamed_roads_get_a_neutral_name():
    analysis = _analyze(index_of(), *_segmented_route())

    assert [s.road_name for s in analysis.segments] == ["Jalan A", "Jalan B", "jalan tanpa nama"]
    assert [(round(s.start_m), round(s.end_m)) for s in analysis.segments] == [(0, 2000), (2000, 3000), (3000, 4000)]
    assert sum(s.length_m for s in analysis.segments) == pytest.approx(analysis.distance_m, abs=1)
    assert [s.index for s in analysis.segments] == [0, 1, 2]


def test_segment_aggregates_count_distinct_incidents_categories_and_historical_hours():
    incidents = [
        incident(1, 1500, east_m=20, category="klitih"),
        incident(2, 1500, east_m=-20, category="klitih"),
        incident(3, 1600, east_m=0, category="penyerangan", when=RECENT.replace(hour=1)),  # dini hari
        incident(4, 2500, east_m=30, category="bentrok antar kelompok"),
    ]

    analysis = _analyze(index_of(*incidents), *_segmented_route())

    a, b, unnamed = analysis.segments
    assert a.incident_count == 3 and a.dominant_category == "klitih"
    assert a.incident_hours == {"malam": 2, "dini_hari": 1}  # sebaran jam kejadian HISTORIS (bukan jam perjalanan)
    assert b.incident_count == 1 and b.dominant_category == "bentrok antar kelompok"
    assert unnamed.incident_count == 0 and unnamed.dominant_category is None


def test_an_incident_near_a_segment_boundary_is_counted_once_for_the_route_but_in_both_segments():
    analysis = _analyze(index_of(incident(1, 2000, east_m=10)), *_segmented_route())

    a, b, _ = analysis.segments
    assert a.incident_count == b.incident_count == 1
    assert analysis.incident_count == 1  # insiden berbeda di tingkat rute


# ================================================================== status (D5)


@pytest.mark.parametrize(
    ("high_m", "medium_m", "any_high", "max_score", "length_m", "expected"),
    [
        (0, 0, False, 0.0, 3000, ROUTE_AMAN),
        (0, 125, False, 4.0, 3000, ROUTE_AMAN),  # sedang pendek
        (0, 399, False, 5.0, 3000, ROUTE_AMAN),
        (0, 400, False, 5.0, 3000, ROUTE_WASPADA),  # sedang cukup panjang
        (125, 250, True, 7.4, 3000, ROUTE_WASPADA),  # tinggi pendek
        (199, 450, True, 7.9, 3000, ROUTE_WASPADA),
        (200, 450, True, 7.9, 3000, ROUTE_BERISIKO_TINGGI),  # tinggi cukup panjang
        (125, 250, True, 8.6, 3000, ROUTE_BERISIKO_TINGGI),  # skor kritis walau pendek
        (150, 150, True, 7.5, 150, ROUTE_BERISIKO_TINGGI),  # rute pendek: ambang dibatasi panjang rute
        (0, 100, False, 4.0, 100, ROUTE_WASPADA),
    ],
)
def test_status_follows_the_documented_exposure_table(high_m, medium_m, any_high, max_score, length_m, expected):
    assert decide_status(high_m, medium_m, any_high, max_score, length_m, SETTINGS) == expected


def test_tc_rte_001_a_route_through_a_high_score_point_is_never_aman_for_any_configuration():
    for high_threshold in (50, 200, 5000):
        for medium_threshold in (100, 400, 5000):
            for critical in (7.5, 8.5, 10.0):
                settings = SETTINGS.model_copy(
                    update={
                        "route_high_exposure_meters": high_threshold,
                        "route_medium_exposure_meters": medium_threshold,
                        "route_critical_score_threshold": critical,
                    }
                )
                for high_m in (1, 125, 600):
                    status = decide_status(high_m, high_m, True, 7.0, 3000, settings)
                    assert status != ROUTE_AMAN


def test_end_to_end_a_cluster_on_the_route_yields_the_expected_status_and_flagged_segment():
    # 10 insiden di satu titik: intensitas tinggi di +-165 m -> beberapa titik cek berlevel tinggi (> 200 m paparan).
    heavy = _analyze(index_of(*cluster(10, 1000)))
    assert heavy.status == ROUTE_BERISIKO_TINGGI and heavy.high_exposure_m >= 200
    assert heavy.segments[0].level == "tinggi" and heavy.segments[0].incident_count == 10

    # 4 insiden persis di satu titik cek (1000 m): hanya satu titik tinggi -> paparan pendek -> waspada.
    short = _analyze(index_of(*cluster(4, 1000)))
    assert short.any_high and short.high_exposure_m < 200 and short.status == ROUTE_WASPADA


def test_never_aman_for_any_cluster_size_that_produces_a_high_point():
    for count in range(4, 14):
        analysis = _analyze(index_of(*cluster(count, 1000)))
        assert analysis.any_high
        assert analysis.status != ROUTE_AMAN


def test_medium_exposure_has_to_be_long_enough_to_become_waspada():
    one_spot = _analyze(index_of(*cluster(2, 1000)))
    assert one_spot.segments[0].level == "sedang" and one_spot.medium_exposure_m < 400
    assert one_spot.status == ROUTE_AMAN  # satu titik sedang pendek: aman, tetapi ruasnya tetap tampil sebagai sedang

    two_spots = _analyze(index_of(*cluster(2, 700), *cluster(2, 1400, start_ident=10)))
    assert two_spots.medium_exposure_m >= 400 and two_spots.status == ROUTE_WASPADA


def test_hour_matters_the_same_cluster_is_harmless_when_travelling_at_noon():
    cluster_at_night = index_of(*cluster(10, 1000))

    at_night = _analyze(cluster_at_night)
    at_noon = _analyze(cluster_at_night, departure=datetime(2026, 9, 21, 12, 0, tzinfo=WIB))

    assert at_night.status == ROUTE_BERISIKO_TINGGI
    assert at_noon.status == ROUTE_AMAN and at_noon.max_score == 0.0  # siang tidak bersebelahan dengan malam


# ===================================================================== alasan (D5)


_FORBIDDEN = ("bahaya", "mengerikan", "mengancam", "korban", "pelaku", "dijamin", "pasti aman", "100% aman", "tewas", "berdarah")


def _reasons(index, *steps, limited=False, named=None):
    analysis = _analyze(index, *steps)
    if named:
        analysis = analysis.__class__(**{**analysis.__dict__, "segments": tuple(
            s.__class__(**{**s.__dict__, "place_name": named}) for s in analysis.segments)})
    return build_reasons(analysis, SETTINGS, limited)


def test_reasons_are_neutral_indonesian_name_the_road_and_never_promise_safety():
    reasons = _reasons(index_of(*cluster(10, 1000, category="penyerangan")), named="Kec. Depok")
    text = " ".join(reasons)

    assert "Melewati Jalan Kaliurang (Kec. Depok): 10 kejadian tercatat dalam radius 300 m dari jalur" in text
    assert "kategori terbanyak penyerangan" in text and "paling sering pada jam malam" in text
    assert "Anda diperkirakan melintas pada jam malam" in text
    assert re.search(r"Sekitar \d+ m jalur melewati area berskor kerawanan tinggi", text)
    assert not any(word in text.lower() for word in _FORBIDDEN)
    assert not re.search(r"-?\d+\.\d{3,}", text)  # tidak ada koordinat


def test_safe_and_limited_routes_carry_an_honest_disclaimer():
    safe = " ".join(_reasons(index_of(*cluster(1, 1000))))
    assert "bukan jaminan keamanan" in safe and "data kejadian yang tercatat" in safe

    no_data = " ".join(_reasons(index_of(), limited=True))
    assert "Belum ada data kejadian di sekitar rute ini" in no_data and "bukan jaminan aman" in no_data


# ================================================================== privasi (D4/D10)


def test_analysis_never_carries_individual_incident_coordinates_or_text():
    secret = incident(1, 1000, east_m=40)  # 40 m dari rute
    analysis = _analyze(index_of(secret, *cluster(3, 1200, east_m=25, start_ident=2)))

    dump = repr(analysis)
    assert f"{secret.latitude:.6f}"[:9] not in dump and f"{secret.longitude:.6f}"[:10] not in dump
    for segment in analysis.segments:  # hanya agregat
        assert set(segment.__dict__) >= {"incident_count", "dominant_category", "incident_hours"}
        assert not hasattr(segment, "incidents")
    assert all(c in ("klitih",) or c is None for c in (s.dominant_category for s in analysis.segments))


# ================================================================ geometri (D6)


def test_simplify_polyline_keeps_endpoints_corners_and_stays_within_tolerance():
    straight = [point_at(d) for d in range(0, 1000, 50)]
    assert simplify_polyline(straight, 15) == (straight[0], straight[-1])  # lurus: hanya ujung

    corner = [*(point_at(d) for d in range(0, 500, 50)), *(point_at(500, east_m) for east_m in range(0, 500, 50))]
    simplified = simplify_polyline(corner, 15)
    assert simplified[0] == corner[0] and simplified[-1] == corner[-1]
    assert point_at(500, 0) in simplified and len(simplified) <= 4  # tikungan dipertahankan

    wiggle = [point_at(d, 6 if (d // 50) % 2 else -6) for d in range(0, 1000, 50)]  # simpangan 6 m < toleransi 15 m
    assert len(simplify_polyline(wiggle, 15)) < len(wiggle)
    assert simplify_polyline(wiggle, 0) == tuple(wiggle)  # toleransi 0 = tanpa penjarangan
    assert simplify_polyline([point_at(0)], 15) == (point_at(0),)


def test_geometry_is_simplified_and_segment_geometries_connect_end_to_start():
    many_points = road("Jalan A", 0, 1000, 300, points=40)
    analysis = _analyze(index_of(), many_points, road("Jalan B", 1000, 2000, 300, points=40))

    assert len(analysis.geometry) <= 4  # 80 titik lurus -> beberapa titik
    first, second = analysis.segments
    assert haversine_meters(first.geometry[-1], second.geometry[0]) < 2  # garis ruas bersambung


def test_sample_route_spacing_endpoints_and_cap():
    points = road("x", 0, 2000, 600).points
    samples = sample_route(points, 125, 400)
    assert samples[0].fraction == 0.0 and samples[-1].fraction == 1.0
    assert len(samples) == pytest.approx(2000 / 125 + 1, abs=2)
    assert len(sample_route(((-7.5, 110.3), (-8.0, 110.3)), 125, 100)) <= 101  # rute sangat panjang dijarangkan


# ============================================================ alternatif (D6/D10)


def _fake_analysis(status, max_score, coverage, duration_s=1000.0):
    return RouteAnalysis(
        status=status, max_score=max_score, high_exposure_m=0, medium_exposure_m=0, any_high=False,
        checked_points=100, covered_points=round(coverage * 100), incident_count=0, segments=(), geometry=(),
        time_buckets=(), seasons=(), distance_m=5000, duration_s=duration_s,
    )


def test_alternative_must_be_clearly_lower_comparable_in_data_and_not_far_slower():
    main = _fake_analysis(ROUTE_BERISIKO_TINGGI, 8.0, 0.8)

    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_WASPADA, 5.0, 0.8)], SETTINGS) == 0  # level lebih rendah
    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_BERISIKO_TINGGI, 7.4, 0.8)], SETTINGS) == 0  # skor turun 0.6
    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_BERISIKO_TINGGI, 7.8, 0.8)], SETTINGS) is None  # selisih sepele
    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_BERISIKO_TINGGI, 9.0, 0.8)], SETTINGS) is None  # lebih buruk


def test_alternative_that_only_looks_safer_because_it_has_little_data_is_not_suggested():
    main = _fake_analysis(ROUTE_BERISIKO_TINGGI, 8.0, 0.8)

    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_AMAN, 0.0, 0.0)], SETTINGS) is None  # tanpa data sama sekali
    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_AMAN, 0.5, 0.3)], SETTINGS) is None  # cakupan 0.3 < 0.8 x 0.8
    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_AMAN, 0.5, 0.7)], SETTINGS) == 0  # sebanding (0.7 >= 0.64)


def test_alternative_much_slower_than_the_main_route_is_not_suggested_and_best_one_wins():
    main = _fake_analysis(ROUTE_BERISIKO_TINGGI, 8.0, 0.8, duration_s=1000)

    assert pick_safer_alternative(main, [_fake_analysis(ROUTE_AMAN, 0.5, 0.8, duration_s=1600)], SETTINGS) is None  # +60%
    best = pick_safer_alternative(
        main,
        [
            _fake_analysis(ROUTE_WASPADA, 5.0, 0.8, duration_s=1100),
            _fake_analysis(ROUTE_AMAN, 1.0, 0.8, duration_s=1400),
            _fake_analysis(ROUTE_AMAN, 1.0, 0.8, duration_s=1200),
        ],
        SETTINGS,
    )
    assert best == 2  # level terendah, skor sama -> yang tercepat


# =============================================================== performa (D9)


def test_checking_a_400_point_route_against_1000_incidents_is_fast():
    # Rute ~50 km dengan 400 titik cek (batas route_max_samples), 1000 insiden tersebar di sepanjang rute.
    steps = [road(f"Jalan {i}", i * 5000, (i + 1) * 5000, 360, points=60) for i in range(10)]
    incidents = [
        IndexedIncident(i, *point_at((i * 50) % 50_000, (i % 7 - 3) * 60), RECENT, time_bucket_of(RECENT), "klitih")
        for i in range(1000)
    ]
    index = IncidentIndex(incidents)
    route = route_of(*steps)

    started = time.perf_counter()
    analysis = analyze_route(route, NIGHT, index, SETTINGS)
    elapsed = time.perf_counter() - started

    print(f"analisis {analysis.checked_points} titik x {len(incidents)} insiden: {elapsed * 1000:.0f} ms")
    assert analysis.checked_points >= 390
    assert elapsed < 3.0  # batas longgar; biasanya jauh di bawah 1 dtk


def test_index_near_matches_a_brute_force_search():
    incidents = [incident(i, (i * 37) % 3000, ((i % 11) - 5) * 80) for i in range(400)]
    index = IncidentIndex(incidents)
    lat, lon = point_at(1500, 0)

    found = {i.ident for i, _ in index.near(lat, lon, 300)}
    brute = {i.ident for i in incidents if haversine_meters((lat, lon), (i.latitude, i.longitude)) <= 300}

    assert found == brute and found
    assert index.any_within(lat, lon, 300) is True and index.any_within(lat + 0.5, lon, 300) is False
