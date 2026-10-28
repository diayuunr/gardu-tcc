import logging
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.risk_agent import WIB
from app.agents.route_agent import (
    FlaggedArea,
    RouteAgentDeps,
    RouteAssessment,
    RouteCheckResult,
    RoutePointError,
)
from app.api import route as route_api
from app.api.route import get_route_agent_deps
from app.core.config import get_settings
from app.core.directions import RouteNotFound, RouteServiceUnavailable
from app.main import app

client = TestClient(app)

ORIGIN = {"text": "Gedongkuning, Kotagede"}
DESTINATION = {"latitude": -7.783, "longitude": 110.367}
VALID_BODY = {"origin": ORIGIN, "destination": DESTINATION}


def _result(level="berisiko_tinggi", narrative=None) -> RouteCheckResult:
    flagged = (
        FlaggedArea("Area -7.815, 110.395", -7.815, 110.395, "malam", 7.6, "tinggi", "Kotagede"),
        FlaggedArea("Area -7.795, 110.365", -7.795, 110.365, "malam", 4.2, "sedang", None),
    )
    return RouteCheckResult(
        assessment=RouteAssessment(level, 7.6, flagged, areas_checked=9, areas_with_data=2),
        origin=(-7.812995, 110.39872),
        destination=(-7.783, 110.367),
        distance_km=4.8,
        duration_minutes=21,
        departure_time=datetime(2026, 9, 20, 22, 0, tzinfo=WIB),
        time_buckets=("malam",),
        narrative=narrative,
        origin_name="Kotagede",
        destination_name=None,  # nama bersifat best-effort: boleh kosong
    )


@pytest.fixture(autouse=True)
def fake_agent(monkeypatch):
    """Ganti agen dengan hasil buatan (logika agen diuji di test_route_agent.py) dan
    catat argumen tiap panggilan."""
    calls: list[dict] = []

    def fake_run(_deps, origin, destination, departure, include_narrative=False):
        calls.append(
            {"origin": origin, "destination": destination, "departure": departure, "narrative": include_narrative}
        )
        return _result(narrative="Rute melewati area yang perlu diwaspadai." if include_narrative else None)

    monkeypatch.setattr(route_api, "run_route_check", fake_run)
    app.dependency_overrides[get_route_agent_deps] = lambda: RouteAgentDeps(supabase=None)
    yield calls
    app.dependency_overrides.pop(get_route_agent_deps, None)


# ------------------------------------------------------------------ jalur normal


def test_returns_risk_indicator_and_areas_to_avoid_and_skips_narrative_by_default(fake_agent):
    response = client.post("/route/check", json=VALID_BODY)

    body = response.json()
    assert response.status_code == 200
    assert body["risk_level"] == "berisiko_tinggi"  # REQ-F-031
    assert [a["place_name"] for a in body["areas_to_avoid"]] == ["Kotagede"]  # REQ-F-032
    assert [a["risk_level"] for a in body["areas_to_watch"]] == ["sedang"]
    assert (body["areas_checked"], body["areas_with_data"], body["duration_minutes"]) == (9, 2, 21)
    assert body["narrative"] is None  # default: tanpa Gemini
    assert (body["origin"]["place_name"], body["destination"]["place_name"]) == ("Kotagede", None)
    assert fake_agent[0]["narrative"] is False
    assert fake_agent[0]["origin"].text == "Gedongkuning, Kotagede"  # teks dirapikan & diteruskan ke agen
    assert (fake_agent[0]["destination"].latitude, fake_agent[0]["destination"].longitude) == (-7.783, 110.367)


def test_include_narrative_flag_reaches_the_agent_and_naive_departure_is_wib(fake_agent):
    departure = (datetime.now(WIB) + timedelta(hours=2)).replace(tzinfo=None, microsecond=0)

    response = client.post(
        "/route/check?include_narrative=true", json={**VALID_BODY, "departure_time": departure.isoformat()}
    )

    assert response.status_code == 200
    assert response.json()["narrative"] == "Rute melewati area yang perlu diwaspadai."
    assert fake_agent[0]["narrative"] is True
    assert fake_agent[0]["departure"] == departure.replace(tzinfo=WIB)  # tanpa zona waktu = WIB


# ---------------------------------------------------------------- validasi API


@pytest.mark.parametrize(
    "body",
    [
        {"origin": ORIGIN},  # tujuan hilang
        {"origin": {}, "destination": DESTINATION},  # titik kosong
        {"origin": {"latitude": -7.8}, "destination": DESTINATION},  # koordinat tidak lengkap
        {"origin": {"text": "x"}, "destination": DESTINATION},  # teks terlalu pendek
        {"origin": {"latitude": 95, "longitude": 110.3}, "destination": DESTINATION},  # lintang di luar rentang
        {**VALID_BODY, "departure_time": "2100-01-01T00:00:00"},  # terlalu jauh di depan
        {**VALID_BODY, "departure_time": "bukan-tanggal"},
    ],
)
def test_invalid_input_is_rejected_at_the_api_level(body, fake_agent):
    assert client.post("/route/check", json=body).status_code == 422
    assert fake_agent == []  # tidak pernah sampai ke agen


def test_include_narrative_must_be_a_boolean(fake_agent):
    assert client.post("/route/check?include_narrative=mungkin", json=VALID_BODY).status_code == 422


# ------------------------------------------------------------ pemetaan error & bocor


@pytest.mark.parametrize(
    ("raised", "status_code", "message_part"),
    [
        (RoutePointError("Lokasi asal tidak ditemukan di wilayah Yogyakarta."), 422, "Lokasi asal tidak ditemukan"),
        (RouteNotFound("no route"), 422, "Rute antara kedua titik tidak ditemukan"),
        (RouteServiceUnavailable("MAPBOX_TOKEN belum diset"), 503, "Layanan peta/rute sedang tidak tersedia"),
    ],
)
def test_domain_errors_map_to_clear_indonesian_messages(monkeypatch, raised, status_code, message_part):
    def failing(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(route_api, "run_route_check", failing)

    response = client.post("/route/check", json=VALID_BODY)

    assert response.status_code == status_code
    assert message_part in response.json()["detail"]
    assert "MAPBOX_TOKEN" not in response.text  # detail konfigurasi internal tidak bocor


def test_unexpected_error_returns_502_and_never_leaks_details(monkeypatch, caplog):
    def failing(*_args, **_kwargs):
        raise RuntimeError("koneksi gagal RAHASIA-DB-DETAIL nomor hp 081234567890")

    monkeypatch.setattr(route_api, "run_route_check", failing)

    with caplog.at_level(logging.DEBUG):
        response = client.post("/route/check", json=VALID_BODY)

    assert response.status_code == 502
    assert "RAHASIA-DB-DETAIL" not in response.text
    assert "RAHASIA-DB-DETAIL" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


# ------------------------------------------------------------------- rate limit


def test_route_checks_are_rate_limited_per_ip_separately_from_reports(monkeypatch):
    monkeypatch.setenv("ROUTE_CHECK_RATE_LIMIT_MAX_REQUESTS", "2")
    get_settings.cache_clear()

    statuses = [client.post("/route/check", json=VALID_BODY).status_code for _ in range(3)]

    assert statuses == [200, 200, 429]
    assert "pemeriksaan rute" in client.post("/route/check", json=VALID_BODY).json()["detail"]
