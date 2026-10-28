"""Tes D2/D3: langkah Directions (nama jalan), kategori insiden, loader & cache indeks insiden."""

import copy
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.agents import incident_index, risk_agent
from app.agents.incident_index import (
    CATEGORY_OTHER,
    fetch_route_incidents,
    get_incident_index,
    invalidate_incident_index,
    normalize_category,
)
from app.agents.risk_agent import WIB
from app.core.config import get_settings
from app.core.directions import fetch_route

TOKEN = "dummy-token-not-real"
ORIGIN, DESTINATION = (-7.78, 110.37), (-7.75, 110.39)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", TOKEN)
    get_settings.cache_clear()
    invalidate_incident_index()
    yield
    get_settings.cache_clear()
    invalidate_incident_index()


# ====================================================================== Directions steps


def _step(name, distance, duration, coords):
    return {"name": name, "distance": distance, "duration": duration, "geometry": {"coordinates": coords}}


def _mapbox_route(steps):
    coords = [c for s in steps for c in s["geometry"]["coordinates"]]
    return {
        "geometry": {"coordinates": coords},
        "distance": sum(s["distance"] for s in steps),
        "duration": sum(s["duration"] for s in steps),
        "legs": [{"steps": steps}],
    }


def _stub(monkeypatch, routes):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"code": "Ok", "routes": routes})

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


STEPS = [
    _step("Jalan Cik Di Tiro", 400.0, 60.0, [[110.37, -7.78], [110.375, -7.775]]),
    _step("", 300.0, 40.0, [[110.375, -7.775], [110.38, -7.77]]),  # tanpa nama
    _step("Jalan Kaliurang", 500.0, 70.0, [[110.38, -7.77], [110.39, -7.75]]),
    _step("Jalan Kaliurang", 0.0, 0.0, [[110.39, -7.75], [110.39, -7.75]]),  # langkah "arrive" tanpa panjang
]


def test_directions_requests_steps_and_parses_road_names_with_geometry(monkeypatch):
    calls = _stub(monkeypatch, [_mapbox_route(STEPS)])

    route = fetch_route(ORIGIN, DESTINATION)

    assert calls[0]["steps"] == "true" and calls[0]["overview"] == "full" and calls[0]["geometries"] == "geojson"
    assert [s.name for s in route.steps] == ["Jalan Cik Di Tiro", "", "Jalan Kaliurang"]  # langkah panjang 0 dibuang
    first = route.steps[0]
    assert first.points == ((-7.78, 110.37), (-7.775, 110.375)) and first.distance_m == 400.0 and first.duration_s == 60.0


def test_malformed_steps_are_dropped_but_the_route_itself_stays_usable(monkeypatch):
    bad = copy.deepcopy(_mapbox_route(STEPS))
    bad["legs"][0]["steps"][1]["geometry"] = {"coordinates": [["x", "y"], [1, 2]]}
    _stub(monkeypatch, [bad])

    route = fetch_route(ORIGIN, DESTINATION)

    assert route.steps == () and len(route.points) >= 2 and route.distance_m > 0  # dinilai sebagai satu jalur


def test_route_without_legs_has_no_steps(monkeypatch):
    plain = copy.deepcopy(_mapbox_route(STEPS))
    del plain["legs"]
    _stub(monkeypatch, [plain])

    assert fetch_route(ORIGIN, DESTINATION).steps == ()


# =========================================================================== kategori


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Klitih (korban pelajar SMP)", "klitih"),
        ("Klitih (dua kejadian beruntun)", "klitih"),
        ("Bentrok antar kelompok", "bentrok antar kelompok"),
        ("Penyerangan dengan gir, korban tewas", "penyerangan"),
        ("penyerangan", "penyerangan"),
        ("pengeroyokan", "penyerangan"),
        ("Dibacok orang tak dikenal", "penyerangan"),
        ("percobaan begal", "begal/penodongan"),
        ("Pencurian motor", "begal/penodongan"),
        ("kejadian mencurigakan", "kejadian mencurigakan"),  # bukan "curi"
        ("pengrusakan", "pengrusakan"),
        ("Korban luka-luka", CATEGORY_OTHER),  # rincian korban tidak diteruskan
        ("energi", CATEGORY_OTHER),
        ("", CATEGORY_OTHER),
        (None, CATEGORY_OTHER),
    ],
)
def test_free_text_incident_types_map_to_a_small_fixed_vocabulary(raw, expected):
    assert normalize_category(raw) == expected


# ================================================================= loader & cache


class _Table:
    def __init__(self, rows, counter):
        self.rows, self.counter = rows, counter
        self._range = (0, 999)
        self.or_expression = None

    def select(self, *_a):
        return self

    def or_(self, expression):
        self.or_expression = expression
        self.counter["or"] = expression
        return self

    def order(self, *_a):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        self.counter["queries"] += 1
        if self.counter.get("fail"):
            raise RuntimeError("db down RAHASIA")
        return SimpleNamespace(data=self.rows[self._range[0] : self._range[1] + 1])


class _Db:
    def __init__(self, rows):
        self.counter = {"queries": 0}
        self.rows = rows

    def table(self, name):
        assert name == "incidents"
        return _Table(self.rows, self.counter)


def _row(lat=-7.75, lon=110.38, when=datetime(2026, 9, 10, 22, 0, tzinfo=WIB), kind="Klitih (korban pelajar SMP)"):
    return {"latitude": lat, "longitude": lon, "incident_time": when.isoformat(), "incident_type": kind}


def test_loader_reads_scored_incidents_normalises_text_and_skips_rows_without_coordinates():
    db = _Db([_row(), _row(lat=None), _row(kind="Penyerangan dengan gir, korban tewas", when=datetime(2026, 9, 11, 2, 0, tzinfo=WIB))])

    incidents = fetch_route_incidents(db)

    assert db.counter["or"] == "is_seed_data.eq.true,status.eq.terverifikasi"  # sumber sama dengan skor (REQ-F-022)
    assert [(i.category, i.bucket) for i in incidents] == [("klitih", "malam"), ("penyerangan", "dini_hari")]
    assert [i.ident for i in incidents] == [0, 1]
    assert not any("korban" in str(i) for i in incidents)  # teks bebas tidak ikut


def test_loader_paginates(monkeypatch):
    monkeypatch.setattr(incident_index, "_PAGE_SIZE", 2)
    db = _Db([_row(lat=-7.75 + i / 1000) for i in range(5)])

    assert len(fetch_route_incidents(db)) == 5
    assert db.counter["queries"] == 3  # 2 + 2 + 1


def test_index_is_cached_then_reloaded_and_a_stale_copy_survives_an_outage(monkeypatch, caplog):
    db = _Db([_row()])

    get_incident_index(db)
    get_incident_index(db)
    assert db.counter["queries"] == 1

    monkeypatch.setenv("ROUTE_INCIDENT_CACHE_SECONDS", "0")
    get_settings.cache_clear()
    invalidate_incident_index()
    get_incident_index(db)
    db.counter["fail"] = True
    assert len(get_incident_index(db)) == 1  # TTL 0 -> baca ulang gagal -> salinan lama dipakai
    assert "RAHASIA" not in caplog.text

    invalidate_incident_index()
    with pytest.raises(RuntimeError):
        get_incident_index(db)  # tanpa salinan sama sekali -> error naik (API -> 502)


def test_recalculating_scores_invalidates_the_incident_cache():
    db = _Db([_row()])
    get_incident_index(db)
    assert db.counter["queries"] == 1

    risk_agent._notify_recalculated()  # dipanggil recalculate_risk_scores setelah skor tersimpan
    get_incident_index(db)

    assert db.counter["queries"] == 2


def test_a_failing_recalculation_listener_never_breaks_recalculation(caplog):
    def broken():
        raise RuntimeError("listener rusak RAHASIA")

    risk_agent.add_recalculation_listener(broken)
    try:
        risk_agent._notify_recalculated()  # tidak boleh melempar
    finally:
        risk_agent._recalculation_listeners.remove(broken)

    assert "RAHASIA" not in caplog.text
