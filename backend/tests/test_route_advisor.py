"""Test Safe Route Advisor."""

from backend.agents.route_advisor import check_route
from backend.db.supabase_client import supabase
from backend.db.queries import upsert_risk_score

TEST_AREA_HIGH = "Area Test Rute Bahaya XYZ"
TEST_AREA_MEDIUM = "Area Test Rute Waspada XYZ"
TIME_SLOT = "siang"
DEPARTURE_TIME_SIANG = "2026-09-20T13:00:00+07:00"


def _cleanup_test_scores():
    supabase.table("risk_scores").delete().in_(
        "area", [TEST_AREA_HIGH, TEST_AREA_MEDIUM]
    ).execute()


def test_check_route_returns_berisiko_tinggi_when_passing_high_risk_area():
    upsert_risk_score(TEST_AREA_HIGH, TIME_SLOT, 90)
    try:
        result = check_route(
            origin=f"Jalan menuju {TEST_AREA_HIGH}",
            destination="Titik tujuan aman",
            departure_time=DEPARTURE_TIME_SIANG,
        )

        assert result["risk_level"] == "berisiko_tinggi"
        assert TEST_AREA_HIGH in result["avoid_areas"]
    finally:
        _cleanup_test_scores()


def test_check_route_returns_aman_when_no_matching_risk_area():
    result = check_route(
        origin="Jalan Tidak Dikenal Nomor 1",
        destination="Jalan Tidak Dikenal Nomor 2",
        departure_time=DEPARTURE_TIME_SIANG,
    )

    assert result["risk_level"] == "aman"


def test_check_route_returns_waspada_for_medium_risk_area():
    upsert_risk_score(TEST_AREA_MEDIUM, TIME_SLOT, 45)
    try:
        result = check_route(
            origin=f"Jalan menuju {TEST_AREA_MEDIUM}",
            destination="Titik tujuan aman",
            departure_time=DEPARTURE_TIME_SIANG,
        )

        assert result["risk_level"] == "waspada"
        assert TEST_AREA_MEDIUM not in result["avoid_areas"]
    finally:
        _cleanup_test_scores()
