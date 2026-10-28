import logging
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from supabase import PostgrestAPIError

import app.api.reports as reports_module
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, row, inserted_records):
        self._row = row
        self._inserted_records = inserted_records

    def insert(self, record):
        self._inserted_records.append(record)
        return self

    def execute(self):
        return _FakeResponse([self._row])


class _FakeSupabase:
    """Pengganti Supabase Client asli, supaya test tidak butuh koneksi jaringan."""

    def __init__(self, row):
        self._row = row
        self.inserted_records: list[dict] = []

    def table(self, name):
        assert name == "reports"
        return _FakeTable(self._row, self.inserted_records)


def _submit_valid_report(fake_supabase, monkeypatch, geocode_result):
    """Submit 1 laporan valid dengan geocoding di-MOCK (test tidak boleh
    memanggil Mapbox asli) dan verification agent tidak dijalankan."""
    monkeypatch.setattr(reports_module, "geocode_location", lambda _text: geocode_result)
    monkeypatch.setattr(reports_module, "process_report_verification", lambda _id: None)
    app.dependency_overrides[get_supabase] = lambda: fake_supabase
    try:
        return client.post(
            "/reports",
            json={
                "description": "Ada sekelompok remaja bawa senjata tajam di simpang jalan.",
                "location_text": "Simpang Jalan Kaliurang km 5",
                "occurred_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)


def test_geocoded_coordinates_are_saved_with_the_report(monkeypatch):
    fake_row = {"id": "22222222-2222-2222-2222-222222222222", "status": "menunggu_verifikasi", "created_at": "2026-09-19T00:00:00+00:00"}
    fake_supabase = _FakeSupabase(fake_row)

    response = _submit_valid_report(fake_supabase, monkeypatch, geocode_result=(-7.7956, 110.3695))

    assert response.status_code == 201
    saved = fake_supabase.inserted_records[0]
    assert saved["latitude"] == -7.7956
    assert saved["longitude"] == 110.3695


def test_report_is_still_saved_with_null_coordinates_when_geocoding_fails(monkeypatch):
    """Geocoding gagal/di luar Yogyakarta (geocode_location -> None) TIDAK boleh
    menolak laporan: koordinat NULL, laporan tetap tersimpan."""
    fake_row = {"id": "33333333-3333-3333-3333-333333333333", "status": "menunggu_verifikasi", "created_at": "2026-09-19T00:00:00+00:00"}
    fake_supabase = _FakeSupabase(fake_row)

    response = _submit_valid_report(fake_supabase, monkeypatch, geocode_result=None)

    assert response.status_code == 201
    saved = fake_supabase.inserted_records[0]
    assert saved["latitude"] is None
    assert saved["longitude"] is None


def test_submit_report_happy_path(monkeypatch):
    occurred_at = datetime.now(timezone.utc) - timedelta(hours=1)
    fake_row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "status": "menunggu_verifikasi",
        "created_at": occurred_at.isoformat(),
    }
    app.dependency_overrides[get_supabase] = lambda: _FakeSupabase(fake_row)
    # Geocoding di-MOCK: test tidak boleh memakai kuota Mapbox asli.
    monkeypatch.setattr(reports_module, "geocode_location", lambda _text: None)
    # Endpoint ini cuma diuji sampai laporan tersimpan — proses verifikasi
    # asli (panggilan AI/network) diuji terpisah di test_verify_agent.py.
    verification_calls: list[str] = []
    monkeypatch.setattr(
        reports_module, "process_report_verification", verification_calls.append
    )
    try:
        response = client.post(
            "/reports",
            json={
                "description": "Ada sekelompok remaja bawa senjata tajam di simpang jalan.",
                "location_text": "Simpang Jalan Kaliurang km 5",
                "occurred_at": occurred_at.isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "menunggu_verifikasi"
    # REQ-NF-120: pastikan tidak ada field identitas pelapor di respons.
    assert "name" not in body and "phone" not in body and "email" not in body
    # Verification agent harus dijadwalkan sebagai background task.
    assert verification_calls == [fake_row["id"]]


def test_failed_insert_returns_502_and_log_never_contains_report_text(monkeypatch, caplog):
    """Error database bisa memuat isi baris (mis. 'Failing row contains ...') —
    log server tidak boleh membawa teks laporan maupun traceback-nya."""
    # Geocoding di-MOCK: test tidak boleh memakai kuota Mapbox asli.
    monkeypatch.setattr(reports_module, "geocode_location", lambda _text: None)

    class _FailingTable:
        def insert(self, _record):
            return self

        def execute(self):
            raise PostgrestAPIError(
                {
                    "message": "null value in column violates not-null constraint",
                    "code": "23502",
                    "hint": None,
                    "details": "Failing row contains (RAHASIA-LAPORAN nomor hp 081234567890)",
                }
            )

    class _FailingSupabase:
        def table(self, _name):
            return _FailingTable()

    app.dependency_overrides[get_supabase] = lambda: _FailingSupabase()
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.post(
                "/reports",
                json={
                    "description": "Laporan uji kegagalan insert, isi tidak boleh bocor ke log.",
                    "location_text": "Jalan Malioboro",
                    "occurred_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                },
            )
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 502
    assert "silakan coba lagi" in response.json()["detail"]
    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert any("code=23502" in record.getMessage() for record in caplog.records)


def test_rate_limiter_blocks_report_after_limit_and_starts_clean_each_test(monkeypatch):
    """REQ-NF-122 + regresi isolasi test: limiter itu state in-memory global.
    Tanpa reset antar test, POST-POST dari test lain di file ini sudah menghabiskan
    jatahnya dan POST pertama di sini langsung kena 429."""
    fake_row = {"id": "44444444-4444-4444-4444-444444444444", "status": "menunggu_verifikasi", "created_at": "2026-09-19T00:00:00+00:00"}
    fake_supabase = _FakeSupabase(fake_row)
    limit = get_settings().rate_limit_max_requests

    statuses = [
        _submit_valid_report(fake_supabase, monkeypatch, geocode_result=None).status_code
        for _ in range(limit + 1)
    ]

    assert statuses == [201] * limit + [429]


def test_submit_report_rejects_empty_description():
    response = client.post(
        "/reports",
        json={
            "description": "   ",
            "location_text": "Jalan Malioboro",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 422
