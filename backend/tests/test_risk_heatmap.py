import logging

import pytest
from fastapi.testclient import TestClient

from app.agents import risk_agent
from app.api import risk as risk_api
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)


def _row(area, bucket, score, level, *, lat=-7.815, lon=110.395, count=1, calculated="2026-09-20T05:00:00+00:00"):
    return {
        "area_name": area, "latitude": lat, "longitude": lon, "time_bucket": bucket,
        "risk_score": score, "risk_level": level, "contributing_incident_count": count,
        "last_calculated_at": calculated,
    }


class _FakeSupabase:
    """Supabase palsu in-memory: select().eq().order().range().execute() atas baris `risk_scores`."""

    def __init__(self, rows):
        self.rows = rows
        self.queries: list[str] = []  # bucket yang diminta tiap query

    def table(self, name):
        assert name == "risk_scores"
        return _Query(self)


class _Query:
    def __init__(self, owner):
        self._owner, self._bucket, self._range = owner, None, None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        assert column == "time_bucket"
        self._bucket = value
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        self._owner.queries.append(self._bucket)
        matched = [row for row in self._owner.rows if row["time_bucket"] == self._bucket]
        start, end = self._range
        return type("Resp", (), {"data": matched[start : end + 1]})()


@pytest.fixture(autouse=True)
def clean_heatmap_cache(monkeypatch):
    monkeypatch.setattr(risk_api, "_heatmap_cache", {})


def _use(fake):
    app.dependency_overrides[get_supabase] = lambda: fake
    return fake


@pytest.fixture(autouse=True)
def restore_dependencies():
    yield
    app.dependency_overrides.pop(get_supabase, None)


def test_returns_only_cells_of_the_requested_bucket_sorted_by_score_with_no_identity_fields():
    fake = _use(_FakeSupabase([
        _row("Area -7.815, 110.395", "malam", 4.17, "sedang"),
        _row("Area -7.795, 110.365", "malam", 6.32, "sedang", lat=-7.795, lon=110.365, count=2,
             calculated="2026-09-20T06:30:00+00:00"),
        _row("Area -7.815, 110.395", "pagi", 9.0, "tinggi"),  # bucket lain: tidak boleh ikut
    ]))

    response = client.get("/risk/heatmap", params={"time_bucket": "malam"})

    body = response.json()
    assert response.status_code == 200
    assert body["time_bucket"] == "malam"
    assert [cell["risk_score"] for cell in body["cells"]] == [6.32, 4.17]  # urut skor tertinggi
    assert set(body["cells"][0]) == {  # REQ-F-042: hanya label area netral, pusat sel, dan angka agregat
        "area_name", "latitude", "longitude", "risk_score", "risk_level", "contributing_incident_count",
    }
    assert body["updated_at"].startswith("2026-09-20T06:30")  # perhitungan terbaru di antara sel
    assert response.headers["cache-control"] == "public, max-age=30"
    assert fake.queries == ["malam"]


def test_defaults_to_the_current_bucket_and_rejects_unknown_buckets(monkeypatch):
    fake = _use(_FakeSupabase([_row("Area -7.815, 110.395", "sore", 3.5, "sedang")]))
    monkeypatch.setattr(risk_api, "time_bucket_of", lambda _moment: "sore")

    default = client.get("/risk/heatmap")
    assert default.status_code == 200 and default.json()["time_bucket"] == "sore"
    assert fake.queries == ["sore"]

    for bad in ("tengah_malam", "MALAM", "malam;drop table risk_scores", ""):
        assert client.get("/risk/heatmap", params={"time_bucket": bad}).status_code == 422  # validasi di API
    assert fake.queries == ["sore"]  # nilai tak valid tidak pernah sampai ke database


def test_database_failure_returns_502_without_leaking_details(caplog):
    class _Broken:
        def table(self, _name):
            raise RuntimeError("koneksi gagal RAHASIA-DB-DETAIL 081234567890")

    _use(_Broken())

    with caplog.at_level(logging.DEBUG):
        response = client.get("/risk/heatmap", params={"time_bucket": "malam"})

    assert response.status_code == 502
    assert "RAHASIA-DB-DETAIL" not in response.text and "RAHASIA-DB-DETAIL" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_result_is_cached_briefly_per_bucket_and_refetched_after_expiry(monkeypatch):
    fake = _use(_FakeSupabase([_row("Area -7.815, 110.395", "malam", 4.17, "sedang")]))

    client.get("/risk/heatmap", params={"time_bucket": "malam"})
    client.get("/risk/heatmap", params={"time_bucket": "malam"})
    assert fake.queries == ["malam"]  # permintaan kedua dari cache: melindungi DB dari lalu lintas publik

    client.get("/risk/heatmap", params={"time_bucket": "pagi"})
    assert fake.queries == ["malam", "pagi"]  # bucket lain punya cache sendiri

    monkeypatch.setattr(risk_api, "_HEATMAP_CACHE_TTL_SECONDS", 0.0)
    risk_api._heatmap_cache.clear()
    client.get("/risk/heatmap", params={"time_bucket": "malam"})
    client.get("/risk/heatmap", params={"time_bucket": "malam"})
    assert fake.queries[-2:] == ["malam", "malam"]  # TTL habis -> baca ulang


def test_all_pages_are_read_and_rows_without_coordinates_are_skipped(monkeypatch):
    monkeypatch.setattr(risk_agent, "_PAGE_SIZE", 2)
    rows = [_row(f"Area {i}", "malam", float(i), "sedang", lat=-7.8 + i / 100, lon=110.3) for i in range(1, 6)]
    rows.append({**_row("Area tanpa koordinat", "malam", 5.0, "sedang"), "latitude": None})
    fake = _use(_FakeSupabase(rows))

    response = client.get("/risk/heatmap", params={"time_bucket": "malam"})

    names = {cell["area_name"] for cell in response.json()["cells"]}
    assert names == {f"Area {i}" for i in range(1, 6)}  # semua halaman terbaca; baris tanpa koordinat dilewati
    # 6 baris / 2 per halaman = 3 halaman penuh + 1 query kosong sebagai penanda akhir data.
    assert len(fake.queries) == 4


def test_empty_bucket_returns_no_cells_and_no_update_time():
    _use(_FakeSupabase([]))

    body = client.get("/risk/heatmap", params={"time_bucket": "dini_hari"}).json()

    assert body == {"time_bucket": "dini_hari", "cells": [], "updated_at": None}
