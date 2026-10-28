"""Tes Fase C: nama wilayah nyata (kecamatan terdekat) untuk sel skor risiko.

C1 pemetaan & penyimpanan saat hitung ulang, C2 pemakaian label di heatmap/score/rute/narasi,
C3 batas jarak dan label netral untuk sel tanpa kecamatan dekat."""

import re
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents import risk_agent, risk_narrator
from app.agents.risk_agent import (
    WIB,
    RiskLookup,
    RiskScoreRow,
    assign_places,
    compute_risk_scores,
    locate_area,
    lookup_risk_score,
    public_label,
    recalculate_risk_scores,
)
from app.agents.risk_narrator import build_narrative_facts, render_facts
from app.core import areas as areas_module
from app.core.areas import Area, AreaDirectory, reset_area_directory_cache
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app
from app.scripts import load_areas

BACKEND = Path(__file__).resolve().parent.parent
REAL_CSV = BACKEND / "data" / "areas_rows.csv"
client = TestClient(app)
CELL = 0.01
NIGHT = datetime(2026, 9, 20, 22, 0, tzinfo=WIB)
GEDONGKUNING = (-7.812995, 110.39872)  # sel "Area -7.815, 110.395"
CELL_LABEL = locate_area(*GEDONGKUNING, CELL)[2]


def _kec(kode, nama, parent, lat, lon):
    return Area(kode, nama, "kecamatan", parent, lat, lon)


def _directory(*extra):
    base = [
        Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
        Area("34.02", "Kabupaten Bantul", "kabkota", None, -7.888, 110.3285),
        _kec("34.71.07", "Kotagede", "34.71", -7.8280, 110.3980),  # dekat Gedongkuning
        _kec("34.71.03", "Gondokusuman", "34.71", -7.7800, 110.3800),
        _kec("34.71.02", "Jetis", "34.71", -7.7800, 110.3600),
        _kec("34.02.09", "Jetis", "34.02", -7.9100, 110.3200),  # nama kembar di Bantul
        Area("34.71.07.1001", "Prenggan", "kelurahan", "34.71.07", -7.8130, 110.3990),  # kelurahan LEBIH dekat
        _kec("34.71.99", "Tanpa Koordinat", "34.71", None, None),
        _kec("34.71.98", "Koordinat Rusak", "34.71", -6.2, 106.8),
        *extra,
    ]
    return AreaDirectory(base)


# ====================================================================== C1/C3: pemetaan murni


def test_cell_is_named_after_the_nearest_kecamatan_centre_not_a_kelurahan_or_broken_rows():
    directory = _directory()

    nearest = directory.nearest_kecamatan(*GEDONGKUNING, 8000)

    assert nearest.nama == "Kotagede"  # bukan kelurahan Prenggan yang lebih dekat, bukan baris tanpa/rusak koordinat
    assert directory.place_name(nearest) == "Kec. Kotagede"


def test_distance_limit_leaves_far_cells_unnamed():
    directory = _directory()

    assert directory.nearest_kecamatan(-8.60, 110.35, 8000) is None  # laut selatan, puluhan km dari kecamatan mana pun
    assert directory.nearest_kecamatan(*GEDONGKUNING, 100) is None  # batas diperketat: Kotagede ~1,7 km
    assert AreaDirectory([]).nearest_kecamatan(*GEDONGKUNING, 8000) is None  # tak ada kecamatan sama sekali


def test_ties_are_broken_by_lowest_kode_so_naming_is_deterministic():
    twins = AreaDirectory([_kec("34.01.02", "B", "34.01", -7.80, 110.30), _kec("34.01.01", "A", "34.01", -7.80, 110.30)])

    assert twins.nearest_kecamatan(-7.80, 110.30, 5000).kode == "34.01.01"


def test_duplicate_kecamatan_names_get_the_parent_for_disambiguation():
    directory = _directory()

    assert directory.place_name(directory.get("34.71.02")) == "Kec. Jetis (Kota Yogyakarta)"
    assert directory.place_name(directory.get("34.02.09")) == "Kec. Jetis (Kabupaten Bantul)"
    assert directory.place_name(directory.get("34.71.03")) == "Kec. Gondokusuman"  # unik: tanpa keterangan


def _row(lat, lon, bucket="malam"):
    centre_lat, centre_lon, label = locate_area(lat, lon, CELL)
    return RiskScoreRow(label, centre_lat, centre_lon, bucket, 4.0, "sedang", 2)


def test_assign_places_names_rows_keeps_the_grid_key_and_leaves_far_rows_neutral():
    near, far = _row(*GEDONGKUNING), _row(-8.60, 110.35)

    named_near, named_far = assign_places([near, far], _directory(), get_settings())

    assert (named_near.place_name, named_near.kecamatan_kode) == ("Kec. Kotagede", "34.71.07")
    assert (named_far.place_name, named_far.kecamatan_kode) == (None, None)
    assert named_near.area_name == near.area_name and named_far.area_name == far.area_name  # kunci unik tidak berubah
    assert (named_near.risk_score, named_near.risk_level, named_near.contributing_incident_count) == (4.0, "sedang", 2)


def test_public_label_prefers_place_name_and_falls_back_to_the_neutral_grid_label():
    assert public_label("Kec. Kotagede", CELL_LABEL) == "Kec. Kotagede"
    assert public_label(None, CELL_LABEL) == CELL_LABEL


@pytest.mark.skipif(not REAL_CSV.exists(), reason="backend/data/areas_rows.csv belum ada")
def test_with_the_real_data_every_kecamatan_centre_maps_to_itself_and_all_labels_are_unique():
    rows = load_areas.read_areas_csv(REAL_CSV).rows
    directory = AreaDirectory([
        Area(r.kode, r.nama, r.tingkat, r.parent_kode, r.latitude, r.longitude) for r in rows
    ])
    kecamatan = directory.find(tingkat="kecamatan")
    assert len(kecamatan) == 78

    for area in kecamatan:
        assert directory.nearest_kecamatan(*area.coordinates, 8000).kode == area.kode
    labels = [directory.place_name(area) for area in kecamatan]
    assert len(set(labels)) == 78  # termasuk dua "Jetis" yang berbeda
    assert sorted(label for label in labels if "Jetis" in label) == [
        "Kec. Jetis (Kabupaten Bantul)", "Kec. Jetis (Kota Yogyakarta)"
    ]
    # Sedikit ke samping dari pusat kecamatan masih menghasilkan kecamatan yang sama; laut tidak bernama.
    gondokusuman = next(a for a in kecamatan if a.nama == "Gondokusuman")
    assert directory.nearest_kecamatan(gondokusuman.coordinates[0] + 0.003, gondokusuman.coordinates[1], 8000).nama == "Gondokusuman"
    assert directory.nearest_kecamatan(-9.2, 110.4, 8000) is None


# ==================================================================== C1: hitung ulang + simpan


class _Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Q:
    def __init__(self, table, op, payload=None):
        self._t, self._op, self._payload = table, op, payload
        self._eq, self._in, self._or, self._range, self._count = [], [], None, None, False

    def select(self, _cols, count=None):
        self._count = count == "exact"
        return self

    def or_(self, expression):
        self._or = [tuple(part.split(".eq.")) for part in expression.split(",")]
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        return self

    def in_(self, k, vs):
        self._in.append((k, list(vs)))
        return self

    def order(self, _c):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, _n):
        return self

    def _ok(self, row):
        if any(row.get(k) != v for k, v in self._eq) or any(row.get(k) not in vs for k, vs in self._in):
            return False
        coerce = {"true": True, "false": False}
        return not self._or or any(row.get(k) == coerce.get(v, v) for k, v in self._or)

    def execute(self):
        if self._t.fail:
            raise RuntimeError("database down")
        rows = self._t.rows
        if self._op == "select":
            matched = [dict(r) for r in rows if self._ok(r)]
            total = len(matched)
            if self._range:
                matched = matched[self._range[0] : self._range[1] + 1]
            return _Resp(matched, count=total if self._count else None)
        if self._op == "upsert":
            for item in self._payload:
                existing = next((r for r in rows if (r["area_name"], r["time_bucket"]) == (item["area_name"], item["time_bucket"])), None)
                existing.update(item) if existing else rows.append({"id": str(uuid.uuid4()), **item})
            return _Resp(self._payload)
        if self._op == "delete":
            doomed = [r for r in rows if self._ok(r)]
            rows[:] = [r for r in rows if r not in doomed]
            return _Resp(doomed)
        raise AssertionError(self._op)


class _T:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows if rows is not None else [], fail

    def select(self, cols, count=None):
        return _Q(self, "select").select(cols, count=count)

    def upsert(self, payload, on_conflict):
        return _Q(self, "upsert", payload)

    def delete(self):
        return _Q(self, "delete")


class _Db:
    def __init__(self, incidents, scores=None, areas=None, areas_fail=False):
        self.tables = {"incidents": _T(incidents), "risk_scores": _T(scores), "areas": _T(areas, fail=areas_fail)}

    def table(self, name):
        return self.tables[name]


def _area_rows():
    return [
        {"kode": a.kode, "nama": a.nama, "tingkat": a.tingkat, "parent_kode": a.parent_kode, "latitude": a.latitude, "longitude": a.longitude}
        for a in _directory()._by_kode.values()
    ]


def _incident():
    return {
        "id": str(uuid.uuid4()), "latitude": GEDONGKUNING[0], "longitude": GEDONGKUNING[1],
        "incident_time": datetime(2022, 4, 6, 22, 0, tzinfo=WIB).isoformat(), "is_seed_data": True, "status": "baru",
    }


@pytest.fixture(autouse=True)
def _fresh_directory_cache():
    reset_area_directory_cache()
    yield
    reset_area_directory_cache()


def test_recalculation_stores_place_name_and_kecamatan_code_without_changing_the_unique_key():
    db = _Db([_incident()], areas=_area_rows())

    result = recalculate_risk_scores(NIGHT, supabase=db)

    [stored] = db.tables["risk_scores"].rows
    assert result.names_resolved is True
    assert (stored["area_name"], stored["time_bucket"]) == (CELL_LABEL, "malam")  # kunci tetap label grid
    assert (stored["place_name"], stored["kecamatan_kode"]) == ("Kec. Kotagede", "34.71.07")


def test_unreadable_or_empty_area_data_never_erases_existing_labels(caplog):
    previous = {"id": "s-1", "area_name": CELL_LABEL, "time_bucket": "malam", "place_name": "Kec. Kotagede", "kecamatan_kode": "34.71.07"}

    for db in (
        _Db([_incident()], scores=[dict(previous)], areas_fail=True),  # tabel areas tak terbaca / belum ada
        _Db([_incident()], scores=[dict(previous)], areas=[]),  # tabel areas kosong
    ):
        reset_area_directory_cache()
        result = recalculate_risk_scores(NIGHT, supabase=db)

        [stored] = db.tables["risk_scores"].rows
        assert result.names_resolved is False and result.upserted == 1  # skor tetap dihitung ulang
        assert stored["place_name"] == "Kec. Kotagede" and stored["kecamatan_kode"] == "34.71.07"  # label lama aman


def test_cell_without_a_nearby_kecamatan_is_stored_with_null_names():
    far = {**_incident(), "latitude": -8.60, "longitude": 110.35}
    db = _Db([far], areas=_area_rows())

    recalculate_risk_scores(NIGHT, supabase=db)

    [stored] = db.tables["risk_scores"].rows
    assert stored["place_name"] is None and stored["kecamatan_kode"] is None
    assert stored["area_name"].startswith("Area -8.")  # tetap punya label grid netral


def test_migration_adds_place_columns_without_touching_the_unique_key_and_is_reversible():
    sql = (BACKEND / "supabase" / "migrations" / "20260923000000_risk_scores_place_name.sql").read_text(encoding="utf-8")
    down = (BACKEND / "supabase" / "migrations" / "20260923000000_risk_scores_place_name_down.sql").read_text(encoding="utf-8")

    assert "add column if not exists place_name text" in sql
    assert "kecamatan_kode text references areas (kode) on delete set null" in sql
    assert not re.search(r"unique|primary key|drop constraint", sql, re.I)  # (area_name, time_bucket) tak diubah
    assert "drop column if exists place_name" in down and "drop column if exists kecamatan_kode" in down


# ====================================================================== C2: label di keluaran


def _score_row(**overrides):
    row = {
        "area_name": CELL_LABEL, "time_bucket": "malam", "risk_score": 4.0, "risk_level": "sedang",
        "contributing_incident_count": 2, "latitude": -7.815, "longitude": 110.395,
        "last_calculated_at": "2026-09-20T05:00:00+00:00", "place_name": "Kec. Kotagede",
    }
    row.update(overrides)
    return row


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _RowsQuery(self._rows)


class _RowsQuery:
    def __init__(self, rows):
        self._rows, self._filters, self._range = rows, [], None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self._filters.append((c, {v}))
        return self

    def in_(self, c, vs):
        self._filters.append((c, set(vs)))
        return self

    def order(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r[c] in v for c, v in self._filters)]
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        return SimpleNamespace(data=rows)


@pytest.fixture
def pinned_today(monkeypatch):
    from datetime import date

    monkeypatch.setattr(risk_agent, "today_wib", lambda: date(2026, 9, 20))


def test_score_lookup_and_endpoint_expose_place_name_and_a_display_label(pinned_today):
    named = lookup_risk_score(_Rows([_score_row()]), *GEDONGKUNING, NIGHT)
    assert named.place_name == "Kec. Kotagede"

    app.dependency_overrides[get_supabase] = lambda: _Rows([_score_row(), _score_row(time_bucket="pagi", place_name=None)])
    try:
        with_name = client.get("/risk/score", params={"lat": GEDONGKUNING[0], "lon": GEDONGKUNING[1], "at": "2026-09-20T22:30:00"}).json()
        without = client.get("/risk/score", params={"lat": GEDONGKUNING[0], "lon": GEDONGKUNING[1], "at": "2026-09-20T09:30:00"}).json()
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert (with_name["place_name"], with_name["label"], with_name["area_name"]) == ("Kec. Kotagede", "Kec. Kotagede", CELL_LABEL)
    assert (without["place_name"], without["label"]) == (None, CELL_LABEL)  # C3: label netral untuk sel tanpa kecamatan dekat


def test_heatmap_cells_carry_place_name_and_label_and_nothing_individual(pinned_today, monkeypatch):
    from app.api import risk as risk_api

    monkeypatch.setattr(risk_api, "_heatmap_cache", {})
    app.dependency_overrides[get_supabase] = lambda: _Rows([
        _score_row(),
        _score_row(area_name="Area -8.605, 110.355", place_name=None, latitude=-8.605, longitude=110.355, risk_score=3.5),
    ])
    try:
        body = client.get("/risk/heatmap", params={"time_bucket": "malam"}).json()
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    cells = {c["area_name"]: c for c in body["cells"]}
    assert cells[CELL_LABEL]["label"] == "Kec. Kotagede"
    assert cells["Area -8.605, 110.355"]["label"] == "Area -8.605, 110.355"
    assert set(cells[CELL_LABEL]) == {
        "area_name", "place_name", "label", "latitude", "longitude", "risk_score", "risk_level", "contributing_incident_count",
    }  # REQ-F-042: tetap hanya agregat


def test_risk_narration_facts_include_the_region_name_only_when_known():
    named = build_narrative_facts(
        RiskLookup(CELL_LABEL, "malam", 4.0, "sedang", 2, True, place_name="Kec. Kotagede"), get_settings()
    )
    unnamed = build_narrative_facts(RiskLookup(CELL_LABEL, "malam", 4.0, "sedang", 2, True), get_settings())

    assert "- Wilayah: Kec. Kotagede" in render_facts(named)
    assert "Wilayah" not in render_facts(unnamed)
    assert "Area -7." not in render_facts(named) + render_facts(unnamed)  # koordinat grid tidak ikut ke Gemini
    assert risk_narrator._SYSTEM_PROMPT  # prompt memuat aturan nama wilayah
    assert "selain nama wilayah yang diberikan" in " ".join(risk_narrator._SYSTEM_PROMPT.split())


# (Nama ruas/kecamatan pada rute diuji di test_route_analysis.py: rute kini memakai analisis kedekatan insiden.)


def test_compute_scores_stay_free_of_place_names_until_assigned():
    [row] = [r for r in compute_risk_scores(
        [risk_agent.ScorableIncident(*GEDONGKUNING, NIGHT)], NIGHT, get_settings().model_copy(update={"risk_neighbor_weight": 0.0})
    )]

    assert (row.place_name, row.kecamatan_kode) == (None, None)  # compute tetap murni; penamaan langkah terpisah
