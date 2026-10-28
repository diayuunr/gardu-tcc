import logging

from fastapi.testclient import TestClient

from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)


class _HealthyDb:
    def table(self, name):
        assert name == "risk_scores"
        return self

    def select(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return object()


def test_health_check_returns_ok_when_database_is_reachable():
    app.dependency_overrides[get_supabase] = lambda: _HealthyDb()
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_check_returns_503_without_leaking_details_when_database_is_down(caplog):
    class _BrokenDb(_HealthyDb):
        def execute(self):
            raise RuntimeError("koneksi gagal ke db.RAHASIA-HOST.supabase.co key=RAHASIA-KEY")

    app.dependency_overrides[get_supabase] = lambda: _BrokenDb()
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.get("/health")
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}
    assert "RAHASIA" not in response.text and "RAHASIA" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_unknown_route_returns_404_in_indonesian():
    response = client.get("/route-yang-tidak-ada")
    assert response.status_code == 404
    assert response.json() == {"detail": "Alamat yang diminta tidak ditemukan."}
