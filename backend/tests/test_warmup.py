"""Pemanasan cache saat startup: mengisi direktori, dan kegagalannya tidak pernah menjatuhkan server."""

import logging

from fastapi.testclient import TestClient

from app.core import warmup
from app.core.areas import Area, AreaDirectory
from app.main import app


def test_warmup_loads_the_directory_once_through_the_given_client():
    calls = []

    def loader(client):
        calls.append(client)
        return AreaDirectory([Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.8, 110.37)])

    assert warmup.warm_caches(lambda: "klien-db", loader) is True
    assert calls == ["klien-db"]


def test_warmup_failure_is_swallowed_and_never_logs_the_error_details(caplog):
    def broken_client():
        raise RuntimeError("SUPABASE_KEY=rahasia-sekali belum diisi")

    with caplog.at_level(logging.DEBUG):
        assert warmup.warm_caches(broken_client, lambda _c: None) is False

    assert "rahasia-sekali" not in caplog.text


def test_warmup_reports_false_when_the_directory_is_unavailable():
    assert warmup.warm_caches(lambda: object(), lambda _c: None) is False


def test_server_startup_starts_the_warmup_thread_and_can_disable_it(monkeypatch):
    started = []
    monkeypatch.setattr("app.main.start_warmup_thread", lambda: started.append(True))

    with TestClient(app):
        pass
    assert started == [True]

    monkeypatch.setattr("app.main.settings", type("S", (), {"startup_warmup_enabled": False})())
    with TestClient(app):
        pass
    assert started == [True]  # dimatikan lewat konfigurasi: tidak jalan lagi
