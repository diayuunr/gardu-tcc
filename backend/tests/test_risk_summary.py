"""Tes GET /risk/summary: agregasi skor per kecamatan."""

import logging
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import risk_agent
from app.agents.risk_agent import RiskCell, summarize_by_kecamatan
from app.api import risk as risk_api
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)


def _row(area, kode, place, score, level, count, bucket="malam", calculated="2026-09-20T05:00:00+00:00"):
    return {
        "area_name": area, "latitude": -7.8, "longitude": 110.4, "time_bucket": bucket, "risk_score": score,
        "risk_level": level, "contributing_incident_count": count, "last_calculated_at": calculated,
        "place_name": place, "kecamatan_kode": kode,
    }


ROWS = [
    _row("Area A", "34.71.07", "Kec. Kotagede", 4.0, "sedang", 2),
    _row("Area B", "34.71.07", "Kec. Kotagede", 7.5, "tinggi", 5, calculated="2026-09-20T06:30:00+00:00"),
    _row("Area C", "34.71.03", "Kec. Gondokusuman", 3.4, "sedang", 1),
    _row("Area D", "34.02.05", "Kec. Kasihan", 7.5, "tinggi", 9),  # skor sama dengan Kotagede, insiden lebih banyak
    _row("Area E", None, None, 6.0, "sedang", 3),  # tanpa kecamatan dekat
    _row("Area F", "34.71.03", "Kec. Gondokusuman", 1.0, "rendah", 0, bucket="pagi"),  # bucket lain
]


class _Db:
    def __init__(self, rows):
        self.rows, self.queries = rows, 0

    def table(self, name):
        assert name == "risk_scores"
        return _Query(self)


class _Query:
    def __init__(self, owner):
        self._owner, self._bucket, self._range = owner, None, (0, 999)

    def select(self, *_a):
        return self

    def eq(self, column, value):
        assert column == "time_bucket"
        self._bucket = value
        return self

    def order(self, *_a):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        self._owner.queries += 1
        rows = [r for r in self._owner.rows if r["time_bucket"] == self._bucket]
        return SimpleNamespace(data=rows[self._range[0] : self._range[1] + 1])


@pytest.fixture(autouse=True)
def _isolation(monkeypatch):
    monkeypatch.setattr(risk_api, "_heatmap_cache", {})
    monkeypatch.setattr(risk_api, "_summary_cache", {})
    monkeypatch.setattr(risk_agent, "today_wib", lambda: date(2026, 9, 20))  # di luar musim Ramadan
    yield
    app.dependency_overrides.pop(get_supabase, None)


def _use(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return db


def test_regions_are_aggregated_per_kecamatan_and_sorted_by_highest_score_then_incidents():
    _use(_Db(ROWS))

    body = client.get("/risk/summary", params={"time_bucket": "malam"}).json()

    assert body["time_bucket"] == "malam"
    assert [r["place_name"] for r in body["regions"]] == ["Kec. Kasihan", "Kec. Kotagede", "Kec. Gondokusuman"]
    kotagede = body["regions"][1]
    assert kotagede == {
        "kecamatan_kode": "34.71.07", "place_name": "Kec. Kotagede", "label": "Kec. Kotagede",
        "risk_score": 7.5, "risk_level": "tinggi", "cell_count": 2, "incident_count": 7,  # skor tertinggi, 2 sel, 2+5 insiden
    }
    assert body["unassigned_cell_count"] == 1  # Area E tak punya kecamatan: dihitung, tidak ditampilkan
    assert body["updated_at"].startswith("2026-09-20T06:30")
    assert all(r["cell_count"] >= 1 for r in body["regions"])


def test_summary_exposes_no_cell_coordinates_cell_labels_or_individual_data():
    _use(_Db(ROWS))

    raw = client.get("/risk/summary", params={"time_bucket": "malam"}).text

    for forbidden in ("latitude", "longitude", "area_name", "Area A", "-7.8", "110.4", "description", "location_text"):
        assert forbidden not in raw
    assert set(client.get("/risk/summary", params={"time_bucket": "malam"}).json()["regions"][0]) == {
        "kecamatan_kode", "place_name", "label", "risk_score", "risk_level", "cell_count", "incident_count",
    }


def test_level_comes_from_the_final_score_including_the_seasonal_multiplier(monkeypatch):
    rows = [_row("Area A", "34.71.07", "Kec. Kotagede", 2.83, "rendah", 1)]  # skor dasar 2.83 = rendah di luar musim
    _use(_Db(rows))

    normal = client.get("/risk/summary", params={"time_bucket": "malam"}).json()["regions"][0]
    risk_api._summary_cache.clear()
    monkeypatch.setattr(risk_agent, "today_wib", lambda: date(2027, 1, 30))  # jelang Ramadan: x1.3
    pre_ramadan = client.get("/risk/summary", params={"time_bucket": "malam"}).json()["regions"][0]

    assert (normal["risk_score"], normal["risk_level"]) == (2.83, "rendah")
    assert pre_ramadan["risk_score"] == pytest.approx(3.68, abs=0.01) and pre_ramadan["risk_level"] == "sedang"


def test_summary_is_cached_per_bucket_and_defaults_to_the_current_bucket(monkeypatch):
    db = _use(_Db(ROWS))

    client.get("/risk/summary", params={"time_bucket": "malam"})
    client.get("/risk/summary", params={"time_bucket": "malam"})
    assert db.queries == 1  # permintaan kedua dari cache
    client.get("/risk/summary", params={"time_bucket": "pagi"})
    assert db.queries == 2

    monkeypatch.setattr(risk_api, "time_bucket_of", lambda _moment: "pagi")
    assert client.get("/risk/summary").json()["time_bucket"] == "pagi"


def test_summary_of_an_empty_bucket_and_invalid_input():
    _use(_Db(ROWS))

    empty = client.get("/risk/summary", params={"time_bucket": "dini_hari"}).json()
    assert empty == {"time_bucket": "dini_hari", "regions": [], "unassigned_cell_count": 0, "updated_at": None}

    bad = client.get("/risk/summary", params={"time_bucket": "tengah_malam"})
    assert bad.status_code == 422 and "nilai tidak valid" in bad.json()["detail"]


def test_database_failure_returns_502_without_leaking_details(caplog):
    class _Broken:
        def table(self, _name):
            raise RuntimeError("koneksi gagal RAHASIA-DB 081234567890")

    _use(_Broken())

    with caplog.at_level(logging.DEBUG):
        response = client.get("/risk/summary", params={"time_bucket": "malam"})

    assert response.status_code == 502
    assert "RAHASIA-DB" not in response.text and "RAHASIA-DB" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_pure_aggregation_ignores_cells_without_a_kecamatan_and_is_deterministic():
    def cell(kode, place, score, count):
        return RiskCell("x", 0.0, 0.0, "malam", score, "sedang", count, None, place_name=place, kecamatan_kode=kode)

    cells = [cell("A", "Kec. A", 5.0, 1), cell("B", "Kec. B", 5.0, 4), cell(None, None, 9.0, 4), cell("A", "Kec. A", 2.0, 2)]

    regions, unassigned = summarize_by_kecamatan(cells)

    assert [r.place_name for r in regions] == ["Kec. B", "Kec. A"]  # skor sama -> insiden lebih banyak dulu
    assert unassigned == 1 and regions[1].cell_count == 2 and regions[1].incident_count == 3
