"""Tes Fase B: data wilayah berjenjang (B1 migrasi, B2 loader, B3 geocoder, B4 kolom reports,
B5 skema & teks lokasi server, B6 koordinat & latensi submit, B7 GET /areas)."""

import csv
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.reports as reports_module
from app.agents import verify_agent
from app.api.reports import submit_report
from app.core import areas as areas_module
from app.core.areas import (
    Area,
    AreaDirectory,
    AreasUnavailable,
    RegionError,
    get_area_directory,
    reset_area_directory_cache,
)
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app
from app.schemas.report import ReportCreate
from app.scripts import geocode_areas, load_areas

BACKEND = Path(__file__).resolve().parent.parent
MIGRATIONS = BACKEND / "supabase" / "migrations"
REAL_CSV = BACKEND / "data" / "areas_rows.csv"
client = TestClient(app)
DESC = "Ada sekelompok remaja membawa senjata tajam di simpang jalan Kaliurang."
OCCURRED = lambda: (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()  # noqa: E731


# ----------------------------------------------------------------------------- fake Supabase


class _Resp:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if isinstance(data, list) else None


class _Q:
    def __init__(self, table, op, payload=None, on_conflict=None):
        self._t, self._op, self._payload, self._on_conflict = table, op, payload, on_conflict
        self._filters: list[tuple] = []
        self._range = None

    def select(self, *_a, **_k):
        return self

    def eq(self, k, v):
        self._filters.append(("eq", k, v))
        return self

    def is_(self, k, _v):
        self._filters.append(("null", k, None))
        return self

    def in_(self, k, vs):
        self._filters.append(("in", k, list(vs)))
        return self

    def order(self, _c):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, _n):
        return self

    def _ok(self, row):
        for kind, k, v in self._filters:
            if kind == "eq" and row.get(k) != v:
                return False
            if kind == "null" and row.get(k) is not None:
                return False
            if kind == "in" and row.get(k) not in v:
                return False
        return True

    def execute(self):
        t = self._t
        if t.fail:
            raise RuntimeError("database down RAHASIA-DB")
        t.queries += 1
        if self._op == "select":
            rows = [dict(r) for r in t.rows if self._ok(r)]
            if self._range:
                rows = rows[self._range[0] : self._range[1] + 1]
            return _Resp(rows)
        if self._op == "insert":
            row = {"id": str(uuid.uuid4()), "status": "menunggu_verifikasi", "created_at": "2026-09-19T00:00:00+00:00", **self._payload}
            t.rows.append(row)
            return _Resp([row])
        if self._op == "update":
            hit = [r for r in t.rows if self._ok(r)]
            for r in hit:
                r.update(self._payload)
            t.updates.append((self._payload, len(hit)))
            return _Resp(hit)
        if self._op == "upsert":
            key = self._on_conflict
            t.upserts.append(self._payload)
            for item in self._payload:
                existing = next((r for r in t.rows if r.get(key) == item[key]), None)
                existing.update(item) if existing else t.rows.append(dict(item))
            return _Resp(self._payload)
        raise AssertionError(self._op)


class _T:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows if rows is not None else [], fail
        self.queries, self.updates, self.upserts = 0, [], []

    def select(self, *_a, **_k):
        return _Q(self, "select")

    def insert(self, payload):
        return _Q(self, "insert", payload)

    def update(self, payload):
        return _Q(self, "update", payload)

    def upsert(self, payload, on_conflict):
        return _Q(self, "upsert", payload, on_conflict)


class _Db:
    def __init__(self, areas=None, reports=None, fail_areas=False):
        self.tables = {"areas": _T(areas, fail=fail_areas), "reports": _T(reports)}

    def table(self, name):
        return self.tables[name]


def _area(kode, nama, tingkat, parent, lat=None, lon=None):
    return {"kode": kode, "nama": nama, "tingkat": tingkat, "parent_kode": parent, "latitude": lat, "longitude": lon}


def _sample_areas():
    return [
        _area("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557),
        _area("34.04.06", "Depok", "kecamatan", "34.04", -7.7700, 110.3900),
        _area("34.04.06.2001", "Caturtunggal", "kelurahan", "34.04.06", -7.7650, 110.3800),
        _area("34.04.05", "Gamping", "kecamatan", "34.04", None, None),  # tanpa koordinat
        _area("34.04.05.2001", "Ambarketawang", "kelurahan", "34.04.05", None, None),
        _area("34.02", "Kabupaten Bantul", "kabkota", None, -7.888, 110.3285),
        _area("34.02.05", "Kasihan", "kecamatan", "34.02", -7.8300, 110.3300),
        _area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
        _area("34.71.03", "Gondokusuman", "kecamatan", "34.71", -7.7800, 110.3800),
        _area("34.71.03.1001", "Baciro", "kelurahan", "34.71.03", -7.7900, 110.3900),
        _area("34.71.04", "Jauh", "kecamatan", "34.71", -6.2, 106.8),  # koordinat di luar DIY (data rusak)
    ]


@pytest.fixture(autouse=True)
def _clean_directory_cache():
    reset_area_directory_cache()
    yield
    reset_area_directory_cache()


@pytest.fixture
def db():
    database = _Db(areas=_sample_areas())
    app.dependency_overrides[get_supabase] = lambda: database
    yield database
    app.dependency_overrides.pop(get_supabase, None)


def _post(body, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setattr(reports_module, "process_report_verification", lambda _id: None)
    return client.post("/reports", json={"description": DESC, "occurred_at": OCCURRED(), **body})


# =================================================================== B1 + B4: migrasi


def test_areas_migration_guards_format_hierarchy_and_privacy():
    sql = (MIGRATIONS / "20260922000000_create_areas.sql").read_text(encoding="utf-8")

    assert "enable row level security" in sql and 'create policy "public_read_areas"' in sql
    assert "for select using (true)" in sql
    assert not re.search(r"for (insert|update|delete|all)", sql)  # tidak ada policy tulis publik
    assert "parent_kode text references areas (kode)" in sql
    assert "kode like parent_kode || '.%'" in sql
    assert "(latitude is null) = (longitude is null)" in sql
    assert (MIGRATIONS / "20260922000000_create_areas_down.sql").exists()


def test_reports_region_migration_adds_columns_hierarchy_checks_and_marks_jalan_private():
    sql = (MIGRATIONS / "20260922000100_reports_region_columns.sql").read_text(encoding="utf-8")

    for column in ("kabkota_kode", "kecamatan_kode", "kelurahan_kode"):
        assert f"{column} text references areas (kode)" in sql
    assert "kecamatan_kode like kabkota_kode || '.%'" in sql
    assert "kelurahan_kode like kecamatan_kode || '.%'" in sql
    assert "length(jalan) <= 200" in sql
    assert "'client', 'kelurahan', 'kecamatan', 'geocoder'" in sql
    assert "PRIVAT" in sql and "JANGAN dipublikasikan" in sql
    assert "enable row level security" not in sql  # RLS reports tetap dari migrasi awal (tanpa baca publik)
    down = (MIGRATIONS / "20260922000100_reports_region_columns_down.sql").read_text(encoding="utf-8")
    assert "drop column if exists jalan" in down


@pytest.mark.skipif(not REAL_CSV.exists(), reason="backend/data/areas_rows.csv belum ada")
def test_every_row_of_the_real_csv_satisfies_the_sql_check_constraints():
    sql = (MIGRATIONS / "20260922000000_create_areas.sql").read_text(encoding="utf-8")
    patterns = dict(re.findall(r"tingkat = '(\w+)' and kode ~ '([^']+)'", sql))
    assert set(patterns) == {"kabkota", "kecamatan", "kelurahan"}

    with open(REAL_CSV, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        assert re.search(patterns[row["tingkat"]], row["kode"]), row["kode"]  # areas_kode_format
        if row["tingkat"] != "kabkota":
            assert row["kode"].startswith(row["parent_kode"] + ".")  # areas_parent_consistent
        else:
            assert not row["parent_kode"]


# ===================================================================== B2: load_areas


@pytest.mark.skipif(not REAL_CSV.exists(), reason="backend/data/areas_rows.csv belum ada")
def test_real_csv_is_valid_with_the_expected_counts_and_old_area_column_is_kept_but_optional():
    result = load_areas.read_areas_csv(REAL_CSV)

    assert result.errors == []
    counts = {t: sum(1 for r in result.rows if r.tingkat == t) for t in ("kabkota", "kecamatan", "kelurahan")}
    assert counts == {"kabkota": 5, "kecamatan": 78, "kelurahan": 438}
    assert all(r.latitude is not None for r in result.rows)
    assert next(r for r in result.rows if r.kode == "34.02").area == "Bantul"  # label lama disimpan apa adanya


def _write_csv(tmp_path, rows, header="area,lat,lng,kode,nama,tingkat,parent_kode", newline="\r\n"):
    path = tmp_path / "areas.csv"
    path.write_bytes(("﻿" + header + newline + newline.join(rows) + newline).encode("utf-8"))
    return path


_OK_ROWS = [
    "34.04,-7.716,110.3557,34.04,Kabupaten Sleman,kabkota,",
    "34.04.06,-7.77,110.39,34.04.06,Depok,kecamatan,34.04",
    "34.04.06.2001,-7.765,110.38,34.04.06.2001,Caturtunggal,kelurahan,34.04.06",
]


def test_loader_reads_bom_and_crlf_and_works_without_the_optional_area_column(tmp_path):
    path = _write_csv(tmp_path, [r.split(",", 1)[1] for r in _OK_ROWS], header="lat,lng,kode,nama,tingkat,parent_kode")

    result = load_areas.read_areas_csv(path)

    assert result.errors == [] and len(result.rows) == 3
    assert all(r.area is None for r in result.rows)


@pytest.mark.parametrize(
    ("bad_row", "expected"),
    [
        ("34.04.07,,,34.04.07,Cangkringan,kecamatan,34.99", "induk '34.99' tidak ada"),
        ("34.04.07,,,34.05.07,Salah,kecamatan,34.04", "diawali kode induk"),  # pola benar, tetapi bukan anak 34.04
        ("34.04.06,,,34.04.06,Depok Kembar,kecamatan,34.04", "kode kembar"),
        ("x,,,34.04.08,Gamping,kapanewon,34.04", "tingkat 'kapanewon' tidak dikenal"),
        ("x,,,34.04.08,Gamping,kecamatan,34.04.06", "bertingkat kecamatan, seharusnya kabkota"),
        ("x,,,34.07,Kota Salah,kabkota,34.04", "tidak boleh punya induk"),
        ("x,-7.7,,34.04.08,Gamping,kecamatan,34.04", "berpasangan"),
        ("x,abc,110.3,34.04.08,Gamping,kecamatan,34.04", "bukan angka"),
        ("x,,,34.04.08,   ,kecamatan,34.04", "nama kosong"),
        ("x,,,34.05.06.2009,Tersasar,kelurahan,34.04.06", "diawali kode induk"),
        ("x,,,34.04.08,Gamping,kecamatan,34.04,ekstra", "melebihi header"),
    ],
)
def test_loader_rejects_each_kind_of_bad_row_with_a_clear_message(tmp_path, bad_row, expected):
    rows = [*_OK_ROWS, bad_row]
    result = load_areas.read_areas_csv(_write_csv(tmp_path, rows))

    assert any(expected in error for error in result.errors), result.errors


def test_loader_flags_missing_header_columns_and_warns_but_accepts_coordinates_outside_diy(tmp_path):
    missing = load_areas.read_areas_csv(_write_csv(tmp_path, ["34.04"], header="kode,nama"))
    assert "kurang kolom" in missing.errors[0]

    outside = _write_csv(tmp_path, [*_OK_ROWS, "x,-6.2,106.8,34.04.09,Luar,kecamatan,34.04"])
    result = load_areas.read_areas_csv(outside)
    assert result.errors == [] and any("di luar DIY" in w for w in result.warnings)


def test_upsert_loads_parents_first_is_idempotent_and_never_erases_existing_coordinates():
    database = _Db(areas=[_area("34.04.06", "Depok", "kecamatan", "34.04", -7.77, 110.39)])  # sudah punya koordinat
    rows = [
        load_areas.AreaRow("34.04.06.2001", "Caturtunggal", "kelurahan", "34.04.06", None, None, "x"),
        load_areas.AreaRow("34.04.06", "Depok", "kecamatan", "34.04", None, None, None),  # CSV kosong untuk baris ini
        load_areas.AreaRow("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557, None),
    ]

    first = load_areas.upsert_areas(database, rows)
    snapshot = [dict(r) for r in database.tables["areas"].rows]
    second = load_areas.upsert_areas(database, rows)

    assert first == second == 3
    assert database.tables["areas"].rows == snapshot  # idempoten
    order = [chunk[0]["tingkat"] for chunk in database.tables["areas"].upserts[:3]]
    assert order == ["kabkota", "kecamatan", "kelurahan"]  # induk lebih dulu (FK)
    depok = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.06")
    assert (depok["latitude"], depok["longitude"]) == (-7.77, 110.39)  # tidak dikosongkan
    no_coordinate_payloads = [p for chunk in database.tables["areas"].upserts for p in chunk if p["kode"] == "34.04.06"]
    assert all("latitude" not in p for p in no_coordinate_payloads)


def test_model_level_location_errors_read_as_one_clean_sentence_without_a_dangling_label(db, monkeypatch):
    response = _post({}, monkeypatch)  # tanpa lokasi apa pun

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Input tidak valid — Isi lokasi kejadian: pilih kabupaten/kota dan kecamatan, atau tulis lokasinya."
    )


def test_loader_cli_dry_run_writes_nothing_and_invalid_csv_aborts_before_touching_the_database(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("database tidak boleh disentuh")

    monkeypatch.setattr(load_areas, "get_supabase", forbidden)

    good = _write_csv(tmp_path, _OK_ROWS)
    assert load_areas.main(["--csv", str(good), "--dry-run"]) == 0

    bad = _write_csv(tmp_path, [*_OK_ROWS, "x,,,34.04.99,Yatim,kecamatan,34.77"])
    assert load_areas.main(["--csv", str(bad)]) == 1
    assert load_areas.main(["--csv", str(tmp_path / "tidak-ada.csv")]) == 1


# ================================================================== B3: geocode_areas


def _geocode_db(rows):
    return _Db(areas=[dict(r) for r in rows])


def _settings(**overrides):
    return get_settings().model_copy(update={"areas_geocode_delay_seconds": 0, **overrides})


def test_geocoder_only_touches_rows_without_valid_coordinates(db):
    database = _geocode_db(_sample_areas())
    queries: list[str] = []

    def fake_geocode(query):
        queries.append(query)
        return (-7.8, 110.4) if "Gamping" in query or "Ambarketawang" in query else None

    report = geocode_areas.geocode_areas(database, dry_run=False, geocode=fake_geocode, settings=_settings())

    # Yang kosong/di luar DIY: Gamping, Ambarketawang, Jauh (di luar DIY). Selebihnya valid -> tidak disentuh.
    assert report.already_valid == 8
    assert sorted(queries) == sorted(q for q in queries if any(n in q for n in ("Gamping", "Ambarketawang", "Jauh")))
    assert len(queries) == 3
    gamping = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.05")
    assert (gamping["latitude"], gamping["longitude"]) == (-7.8, 110.4)
    depok = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.06")
    assert (depok["latitude"], depok["longitude"]) == (-7.77, 110.39)  # koordinat valid tidak ditimpa
    assert [f for f in report.failed] == [("34.71.04", "Jauh")]  # geocoder tak menemukan -> tidak diubah
    assert next(r for r in database.tables["areas"].rows if r["kode"] == "34.71.04")["latitude"] == -6.2


def test_children_are_validated_against_a_parent_filled_earlier_in_the_same_run():
    database = _geocode_db(_sample_areas())
    answers = {"Kecamatan Gamping": (-7.80, 110.32), "Desa Ambarketawang": (-7.801, 110.321)}

    report = geocode_areas.geocode_areas(
        database, dry_run=False, geocode=lambda q: next((v for k, v in answers.items() if q.startswith(k)), None), settings=_settings()
    )

    assert set(report.filled) == {"34.04.05", "34.04.05.2001"}  # kecamatan dulu, lalu kelurahannya divalidasi terhadapnya
    assert report.doubtful == []


def test_result_far_from_parent_or_outside_diy_is_reported_not_written():
    database = _geocode_db(_sample_areas())
    far_from_parent = (-7.95, 110.75)  # di DIY tetapi ~40+ km dari pusat Sleman
    answers = {"Kecamatan Gamping": far_from_parent, "Desa Ambarketawang": (-6.2, 106.8)}

    report = geocode_areas.geocode_areas(
        database, dry_run=False, geocode=lambda q: next((v for k, v in answers.items() if q.startswith(k)), None), settings=_settings()
    )

    reasons = {kode: why for kode, _n, why in report.doubtful}
    assert "dari pusat induk" in reasons["34.04.05"] and "luar DIY" in reasons["34.04.05.2001"]
    assert report.filled == []
    gamping = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.05")
    assert gamping["latitude"] is None  # tidak ada koordinat karangan


def test_child_of_a_parent_without_coordinates_is_doubtful_and_dry_run_writes_nothing():
    rows = [r for r in _sample_areas() if r["kode"] in ("34.04", "34.04.05", "34.04.05.2001")]
    rows[0]["latitude"] = rows[0]["longitude"] = None  # bahkan kabkota kosong
    database = _geocode_db(rows)

    report = geocode_areas.geocode_areas(database, dry_run=True, geocode=lambda _q: (-7.8, 110.4), settings=_settings())

    assert "34.04" in report.unvalidated  # kabkota tak punya induk untuk membandingkan -> ditandai
    assert database.tables["areas"].updates == []  # dry run
    assert report.write_errors == []


def test_write_is_guarded_so_a_concurrently_filled_value_is_not_overwritten():
    database = _geocode_db([r for r in _sample_areas() if r["kode"] in ("34.04", "34.04.05")])
    calls = []

    def geocode_then_someone_else_fills(query):
        calls.append(query)
        target = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.05")
        target["latitude"], target["longitude"] = -7.81, 110.33  # diisi proses lain di antara baca dan tulis
        return (-7.80, 110.32)

    geocode_areas.geocode_areas(database, dry_run=False, geocode=geocode_then_someone_else_fills, settings=_settings())

    gamping = next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.05")
    assert (gamping["latitude"], gamping["longitude"]) == (-7.81, 110.33)  # penjaga is_null mencegah timpa


def test_suspicious_existing_coordinates_are_only_reported_and_delay_is_applied_between_calls():
    rows = _sample_areas()
    next(r for r in rows if r["kode"] == "34.04.06")["latitude"] = -7.95  # ada & di DIY, tetapi ~55 km dari pusat Sleman
    next(r for r in rows if r["kode"] == "34.04.06")["longitude"] = 110.80
    database = _geocode_db(rows)
    sleeps: list[float] = []

    report = geocode_areas.geocode_areas(
        database, dry_run=True, geocode=lambda _q: None, sleep=sleeps.append, settings=get_settings().model_copy(
            update={"areas_geocode_delay_seconds": 0.5, "areas_geocode_max_kecamatan_distance_meters": 20000}
        ),
    )

    # Depok dipindah jauh dari Sleman; kelurahan di bawahnya (Caturtunggal) kini ikut jauh dari Depok.
    assert {k for k, _n, _d in report.suspicious_existing} == {"34.04.06", "34.04.06.2001"}
    assert next(r for r in database.tables["areas"].rows if r["kode"] == "34.04.06")["latitude"] == -7.95  # tidak diubah
    assert len(sleeps) == len(report.failed) - 1 and set(sleeps) == {0.5}


def test_geocoder_errors_on_one_row_do_not_stop_the_others_and_limit_is_respected():
    database = _geocode_db(_sample_areas())

    def flaky(query):
        if "Gamping" in query:
            raise RuntimeError("timeout RAHASIA-QUERY")
        return None

    report = geocode_areas.geocode_areas(database, dry_run=True, geocode=flaky, settings=_settings())
    assert any(kode == "34.04.05" and "RuntimeError" in why for kode, _n, why in report.doubtful)
    assert not any("RAHASIA" in why for _k, _n, why in report.doubtful)

    limited = geocode_areas.geocode_areas(database, dry_run=True, limit=1, geocode=lambda _q: None, settings=_settings())
    assert len(limited.failed) == 1


# ================================================ B5: direktori wilayah, hierarki, teks lokasi


def _directory():
    return AreaDirectory([areas_module._row_to_area(r) for r in _sample_areas()])


def test_resolve_region_accepts_valid_hierarchy_and_rejects_mismatches_without_echoing_codes():
    directory = _directory()

    region = directory.resolve_region("34.04", "34.04.06", "34.04.06.2001")
    assert (region.kabkota.nama, region.kecamatan.nama, region.kelurahan.nama) == ("Kabupaten Sleman", "Depok", "Caturtunggal")
    assert directory.resolve_region("34.04", "34.04.06").kelurahan is None

    cases = [
        (("34.02", "34.04.06"), "bukan bagian dari kabupaten/kota"),  # kecamatan Sleman di bawah Bantul
        (("34.04", "34.04.06", "34.04.05.2001"), "bukan bagian dari kecamatan"),
        (("34.99", "34.04.06"), "tidak ditemukan"),
        (("34.04", "34.04"), "tidak sesuai tingkatnya"),  # kabkota dipakai sebagai kecamatan
        (("34.04.06", "34.04.06"), "tidak sesuai tingkatnya"),
    ]
    for args, message in cases:
        with pytest.raises(RegionError, match=message) as error:
            directory.resolve_region(*args)
        assert "34." not in str(error.value)  # kode kiriman klien tidak digemakan


def test_location_text_is_built_from_area_names_with_kelurahan_or_desa_labels():
    directory = _directory()

    desa = directory.resolve_region("34.04", "34.04.06", "34.04.06.2001")
    assert desa.location_text("Jalan Kaliurang km 5") == (
        "Jalan Kaliurang km 5, Desa Caturtunggal, Kecamatan Depok, Kabupaten Sleman"
    )
    kota = directory.resolve_region("34.71", "34.71.03", "34.71.03.1001")
    assert kota.location_text() == "Kelurahan Baciro, Kecamatan Gondokusuman, Kota Yogyakarta"  # segmen 1xxx = kelurahan
    assert directory.resolve_region("34.04", "34.04.06").location_text() == "Kecamatan Depok, Kabupaten Sleman"


def test_initial_coordinates_prefer_kelurahan_then_kecamatan_and_ignore_invalid_centres():
    directory = _directory()

    assert directory.resolve_region("34.04", "34.04.06", "34.04.06.2001").initial_coordinates() == (-7.765, 110.38, "kelurahan")
    assert directory.resolve_region("34.04", "34.04.06").initial_coordinates() == (-7.77, 110.39, "kecamatan")
    # kelurahan tanpa koordinat -> turun ke kecamatan; keduanya kosong -> None
    assert directory.resolve_region("34.04", "34.04.05", "34.04.05.2001").initial_coordinates() is None
    assert directory.resolve_region("34.71", "34.71.04").initial_coordinates() is None  # koordinat di luar DIY dianggap kosong


# =================================================================== cache direktori


def test_directory_is_cached_reloaded_after_ttl_and_stale_copy_survives_a_database_outage(monkeypatch):
    database = _Db(areas=_sample_areas())

    get_area_directory(database)
    get_area_directory(database)
    assert database.tables["areas"].queries == 1  # pemanggilan kedua dari cache

    monkeypatch.setenv("AREAS_CACHE_TTL_SECONDS", "0")
    get_settings.cache_clear()
    reset_area_directory_cache()
    get_area_directory(database)  # TTL 0 -> setiap kali baca ulang
    database.tables["areas"].fail = True
    assert len(get_area_directory(database)) == len(_sample_areas())  # DB mati: cache lama dipakai, bukan error
    get_settings.cache_clear()


def test_directory_without_cache_and_with_database_down_raises_and_empty_table_is_not_cached(caplog):
    with pytest.raises(AreasUnavailable):
        get_area_directory(_Db(areas=_sample_areas(), fail_areas=True))
    assert "RAHASIA-DB" not in caplog.text

    empty = _Db(areas=[])
    assert len(get_area_directory(empty)) == 0
    empty.tables["areas"].rows.extend(_sample_areas())
    assert len(get_area_directory(empty)) == len(_sample_areas())  # tidak menempel kosong setelah load_areas dijalankan


# ============================================================= B5: skema ReportCreate


def _create(**fields):
    return ReportCreate(description=DESC, occurred_at=datetime.now(timezone.utc) - timedelta(hours=1), **fields)


def test_schema_accepts_region_path_and_legacy_path_and_ignores_client_text_when_codes_are_given():
    region = _create(kabkota_kode="34.04", kecamatan_kode="34.04.06", kelurahan_kode="34.04.06.2001", jalan="Jalan Kaliurang",
                     location_text="TEKS PALSU DARI KLIEN")
    assert region.location_text is None  # dibuang: server menyusun sendiri
    assert _create(kabkota_kode="34.04", kecamatan_kode="34.04.06").kelurahan_kode is None
    assert _create(location_text="Simpang Kaliurang km 5").kabkota_kode is None  # jalur lama


@pytest.mark.parametrize(
    "fields",
    [
        {},  # tanpa lokasi apa pun
        {"kabkota_kode": "34.04"},  # kecamatan wajib
        {"kecamatan_kode": "34.04.06"},
        {"kelurahan_kode": "34.04.06.2001"},
        {"jalan": "Jalan Kaliurang"},  # jalan tanpa wilayah
        {"kabkota_kode": "abc", "kecamatan_kode": "34.04.06"},  # format kode
        {"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06", "kelurahan_kode": "34.04.06.20019"},
    ],
)
def test_schema_rejects_incomplete_or_malformed_location(fields):
    with pytest.raises(ValidationError):
        _create(**fields)


def test_jalan_is_cleaned_limited_to_200_chars_and_refuses_personal_contact_details():
    base = {"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06"}

    assert _create(**base, jalan="  Jalan\t Kaliurang \n km   5\x00  ").jalan == "Jalan Kaliurang km 5"
    assert _create(**base, jalan="   ").jalan is None
    assert len(_create(**base, jalan="a" * 200).jalan) == 200
    with pytest.raises(ValidationError, match="maksimal 200"):
        _create(**base, jalan="a" * 201)
    for personal in ("rumah budi 0812-3456-7890", "hubungi budi@contoh.com"):
        with pytest.raises(ValidationError, match="email atau nomor telepon"):
            _create(**base, jalan=personal)
    assert _create(**base, jalan="Jalan Kaliurang km 5 no. 12A").jalan  # nomor jalan biasa tetap lolos


# ================================================= B5 + B6: endpoint laporan (jalur berjenjang)


def _saved(database):
    return database.tables["reports"].rows[-1]


def test_region_report_stores_codes_server_built_location_and_instant_centre_coordinates(db, monkeypatch):
    response = _post(
        {"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06", "kelurahan_kode": "34.04.06.2001",
         "jalan": "Jalan Kaliurang km 5", "location_text": "TEKS PALSU"},
        monkeypatch,
    )

    assert response.status_code == 201
    saved = _saved(db)
    assert saved["location_text"] == "Jalan Kaliurang km 5, Desa Caturtunggal, Kecamatan Depok, Kabupaten Sleman"
    assert "PALSU" not in saved["location_text"]
    assert (saved["kabkota_kode"], saved["kecamatan_kode"], saved["kelurahan_kode"]) == ("34.04", "34.04.06", "34.04.06.2001")
    assert saved["jalan"] == "Jalan Kaliurang km 5"
    assert (saved["latitude"], saved["longitude"], saved["coordinate_source"]) == (-7.765, 110.38, "kelurahan")
    assert "jalan" not in response.json() and "location_text" not in response.json()


def test_coordinate_fallback_order_client_then_kelurahan_then_kecamatan_then_none(db, monkeypatch):
    base = {"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06"}

    _post({**base, "latitude": -7.80, "longitude": 110.40}, monkeypatch)
    assert (_saved(db)["latitude"], _saved(db)["coordinate_source"]) == (-7.80, "client")

    _post({**base, "latitude": -6.2, "longitude": 106.8}, monkeypatch)  # di luar DIY -> diabaikan (bukan ditolak)
    assert (_saved(db)["latitude"], _saved(db)["coordinate_source"]) == (-7.77, "kecamatan")

    _post(base, monkeypatch)
    assert _saved(db)["coordinate_source"] == "kecamatan"

    _post({"kabkota_kode": "34.04", "kecamatan_kode": "34.04.05", "kelurahan_kode": "34.04.05.2001"}, monkeypatch)
    assert (_saved(db)["latitude"], _saved(db)["coordinate_source"]) == (None, None)  # tak ada pusat valid -> NULL


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"kabkota_kode": "34.02", "kecamatan_kode": "34.04.06"}, "bukan bagian dari kabupaten/kota"),
        ({"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06", "kelurahan_kode": "34.04.05.2001"}, "bukan bagian dari kecamatan"),
        ({"kabkota_kode": "34.99", "kecamatan_kode": "34.99.01"}, "tidak ditemukan"),
    ],
)
def test_hierarchy_is_validated_against_the_areas_table(db, monkeypatch, body, message):
    response = _post(body, monkeypatch)

    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert db.tables["reports"].rows == []  # tidak ada yang tersimpan


def test_region_report_returns_503_when_area_data_is_unavailable_and_nothing_cached(monkeypatch):
    broken = _Db(areas=_sample_areas(), fail_areas=True)
    app.dependency_overrides[get_supabase] = lambda: broken
    try:
        response = _post({"kabkota_kode": "34.04", "kecamatan_kode": "34.04.06"}, monkeypatch)
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 503
    assert "RAHASIA-DB" not in response.text and "sementara tidak dapat" in response.json()["detail"]


def test_legacy_location_text_path_still_works_without_touching_the_areas_table(db, monkeypatch):
    response = _post({"location_text": "Simpang Jalan Kaliurang km 5"}, monkeypatch)

    assert response.status_code == 201
    assert _saved(db)["location_text"] == "Simpang Jalan Kaliurang km 5"
    assert db.tables["areas"].queries == 0


# ===================================================================== B6: latensi submit


def test_submit_returns_before_any_geocoding_even_when_mapbox_is_slow(db, monkeypatch):
    """Dulu geocoding Mapbox sinkron menahan respons 3-19 dtk. Sekarang submit hanya membaca cache wilayah
    dan menyimpan; geocoding yang lambat berjalan SETELAH respons (background task)."""
    geocode_calls: list[str] = []

    def slow_geocode(text):
        geocode_calls.append(text)
        time.sleep(2.0)
        return (-7.77, 110.39)

    monkeypatch.setattr(verify_agent, "geocode_location", slow_geocode)
    assert not hasattr(reports_module, "geocode_location")  # tidak ada lagi jalur geocoding sinkron di endpoint

    payload = ReportCreate(
        description=DESC, occurred_at=datetime.now(timezone.utc) - timedelta(hours=1),
        kabkota_kode="34.04", kecamatan_kode="34.04.06", jalan="Jalan Kaliurang km 5",
    )
    background = BackgroundTasks()
    started = time.perf_counter()
    result = submit_report(payload, background, supabase=db, _rate_limit=None)
    elapsed = time.perf_counter() - started

    print(f"latensi submit (tanpa menunggu geocoding 2 dtk): {elapsed * 1000:.1f} ms")
    assert elapsed < 0.5
    assert geocode_calls == []  # belum dipanggil
    assert len(background.tasks) == 1 and result.status.value == "menunggu_verifikasi"


# ======================================== B6: penyempurnaan koordinat di background (verify_agent)


def _report_row(**overrides):
    row = {
        "id": str(uuid.uuid4()), "location_text": "Jalan Kaliurang km 5, Kecamatan Depok, Kabupaten Sleman",
        "latitude": -7.77, "longitude": 110.39, "coordinate_source": "kecamatan", "jalan": "Jalan Kaliurang km 5",
    }
    row.update(overrides)
    return row


def _refine(row, geocode, monkeypatch, database=None):
    database = database or _Db(reports=[row])
    monkeypatch.setattr(verify_agent, "geocode_location", geocode)
    verify_agent._refine_location(database, row, get_settings())
    return database


def test_precise_geocode_inside_the_allowed_radius_replaces_the_centre_coordinates(monkeypatch):
    row = _report_row()

    database = _refine(row, lambda _t: (-7.7750, 110.4000), monkeypatch)  # ~1,4 km dari pusat kecamatan

    assert (row["latitude"], row["longitude"], row["coordinate_source"]) == (-7.775, 110.4, "geocoder")
    assert database.tables["reports"].rows[0]["coordinate_source"] == "geocoder"


def test_geocode_far_from_the_chosen_area_is_ignored_and_centre_coordinates_are_kept(monkeypatch):
    row = _report_row()

    _refine(row, lambda _t: (-7.95, 110.80), monkeypatch)  # di DIY tetapi > 8 km dari Depok

    assert (row["latitude"], row["coordinate_source"]) == (-7.77, "kecamatan")


def test_no_street_means_no_mapbox_call_and_client_or_geocoded_points_are_never_changed(monkeypatch):
    def must_not_call(_text):
        raise AssertionError("tidak boleh memanggil Mapbox")

    for row in (
        _report_row(jalan=None),  # hanya pusat wilayah yang bisa ditebak ulang: hemat kuota
        _report_row(coordinate_source="client"),
        _report_row(coordinate_source="geocoder"),
        _report_row(coordinate_source=None, latitude=-7.8, longitude=110.4),  # jalur lama yang sudah berkoordinat
    ):
        _refine(row, must_not_call, monkeypatch)


def test_legacy_report_without_coordinates_accepts_any_geocode_inside_diy(monkeypatch):
    row = _report_row(coordinate_source=None, latitude=None, longitude=None, jalan=None, location_text="Simpang Kaliurang km 5")

    _refine(row, lambda _t: (-7.70, 110.40), monkeypatch)

    assert (row["latitude"], row["coordinate_source"]) == (-7.70, "geocoder")


def test_geocoding_or_storage_failures_never_break_verification_and_leave_coordinates_alone(monkeypatch, caplog):
    def boom(_text):
        raise RuntimeError("Mapbox down RAHASIA-ALAMAT")

    row = _report_row()
    _refine(row, boom, monkeypatch)
    assert (row["latitude"], row["coordinate_source"]) == (-7.77, "kecamatan")

    class _FailingUpdate(_Db):
        def table(self, name):
            table = super().table(name)
            table.fail = True
            return table

    row = _report_row()
    _refine(row, lambda _t: (-7.775, 110.4), monkeypatch, database=_FailingUpdate(reports=[row]))
    assert (row["latitude"], row["coordinate_source"]) == (-7.77, "kecamatan")  # tidak tersimpan -> tidak dipakai
    assert "RAHASIA" not in caplog.text


def test_refined_coordinates_are_used_for_the_incident_created_in_the_same_run(monkeypatch):
    class _Rows(_T):
        pass

    report = {
        **_report_row(), "description": DESC, "occurred_at": datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc).isoformat(),
        "incident_id": None, "status": "menunggu_verifikasi", "extracted_incident_type": None,
    }
    database = SimpleNamespace(tables={"reports": _T([report]), "incidents": _T([])})
    database.table = lambda name: database.tables[name]
    database.rpc = lambda *_a, **_k: SimpleNamespace(execute=lambda: _Resp([]))
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: database)
    monkeypatch.setattr(verify_agent, "geocode_location", lambda _t: (-7.775, 110.4))
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: "penyerangan")
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _d: [0.1] * 768)
    monkeypatch.setattr(verify_agent, "refresh_risk_scores_safely", lambda: None)

    verify_agent.process_report_verification(report["id"])

    incident = database.tables["incidents"].rows[0]
    assert (incident["latitude"], incident["longitude"]) == (-7.775, 110.4)  # titik presisi, bukan pusat kecamatan


# ========================================================================== B7: GET /areas


def test_areas_endpoint_lists_by_level_and_parent_sorted_by_name_with_cache_header(db):
    kabkota = client.get("/areas", params={"tingkat": "kabkota"})
    kecamatan = client.get("/areas", params={"tingkat": "kecamatan", "parent": "34.04"})
    kelurahan = client.get("/areas", params={"tingkat": "kelurahan", "parent": "34.04.06"})

    assert [a["nama"] for a in kabkota.json()["areas"]] == ["Kabupaten Bantul", "Kabupaten Sleman", "Kota Yogyakarta"]
    assert kabkota.json()["count"] == 3
    assert [a["kode"] for a in kecamatan.json()["areas"]] == ["34.04.06", "34.04.05"]  # Depok, Gamping (urut nama)
    assert [a["nama"] for a in kecamatan.json()["areas"]] == sorted(a["nama"] for a in kecamatan.json()["areas"])
    assert [a["nama"] for a in kelurahan.json()["areas"]] == ["Caturtunggal"]
    assert kabkota.headers["cache-control"] == "public, max-age=300"
    assert set(kabkota.json()["areas"][0]) == {"kode", "nama", "tingkat", "parent_kode", "latitude", "longitude"}


def test_areas_endpoint_hides_invalid_coordinates_and_uses_the_cache_between_calls(db):
    body = client.get("/areas", params={"tingkat": "kecamatan", "parent": "34.71"}).json()
    jauh = next(a for a in body["areas"] if a["nama"] == "Jauh")
    assert (jauh["latitude"], jauh["longitude"]) == (None, None)  # koordinat di luar DIY tidak dibocorkan sebagai data valid

    client.get("/areas")
    client.get("/areas")
    assert db.tables["areas"].queries == 1


def test_areas_endpoint_validates_input_in_indonesian_and_reports_unavailability(monkeypatch):
    app.dependency_overrides[get_supabase] = lambda: _Db(areas=_sample_areas())
    try:
        bad_level = client.get("/areas", params={"tingkat": "provinsi"})
        bad_parent = client.get("/areas", params={"parent": "bukan-kode"})
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert bad_level.status_code == bad_parent.status_code == 422
    assert "Input tidak valid" in bad_level.json()["detail"] and "format tidak valid" in bad_parent.json()["detail"]

    app.dependency_overrides[get_supabase] = lambda: _Db(areas=_sample_areas(), fail_areas=True)
    try:
        down = client.get("/areas")
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    assert down.status_code == 503 and "RAHASIA-DB" not in down.text
