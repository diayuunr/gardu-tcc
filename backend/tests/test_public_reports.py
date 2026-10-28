"""Fase E1: GET /reports/public dan GET /reports/stats — publik, anonim, dipaginasi, di-cache; tes privasi."""

import logging

import pytest
from db_fake import FakeDb
from fastapi.testclient import TestClient

from app.api import reports_public
from app.core import rate_limit
from app.core.areas import Area, AreaDirectory
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)

DIRECTORY = AreaDirectory([
    Area("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557),
    Area("34.04.06", "Depok", "kecamatan", "34.04", -7.7700, 110.3900),
    Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
    Area("34.71.02", "Jetis", "kecamatan", "34.71", -7.7800, 110.3600),
])

SECRET_DESCRIPTION = "RAHASIA-deskripsi: korban bernama Budi dibacok di depan rumah nomor 12"
SECRET_STREET = "RAHASIA-jalan Gang Mawar 7"
PRIVATE_KEYS = {"description", "jalan", "location_text", "latitude", "longitude", "id", "incident_id", "embedding"}


def _report(n, status="terverifikasi", **overrides):
    row = {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "public_number": n,
        "status": status,
        "description": SECRET_DESCRIPTION,
        "jalan": SECRET_STREET,
        "location_text": f"{SECRET_STREET}, Depok, Sleman",
        "latitude": -7.7702,
        "longitude": 110.3902,
        "kecamatan_kode": "34.04.06",
        "occurred_at": "2026-10-20T22:47:31+07:00",
        "created_at": f"2026-10-21T10:{n:02d}:00+00:00",
        "extracted_incident_type": "penyerangan dengan senjata tajam",
        "incident_type_hint": None,
        "incident_id": "11111111-1111-4111-8111-111111111111",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reports_public.clear_public_cache()
    rate_limit._request_log.clear()
    monkeypatch.setattr(reports_public, "get_directory_or_none", lambda _db: DIRECTORY)
    yield
    app.dependency_overrides.pop(get_supabase, None)
    reports_public.clear_public_cache()
    rate_limit._request_log.clear()


def _use(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return db


def _list(**params):
    return client.get("/reports/public", params=params)


# =============================================================== daftar publik


def test_public_list_exposes_only_the_five_allowed_fields_and_none_of_the_private_content():
    _use(FakeDb(reports=[_report(1), _report(2, status="menunggu_verifikasi")]))

    response = _list()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"total", "limit", "offset", "items"} and body["total"] == 2
    for item in body["items"]:
        assert set(item) == {"nomor", "status", "occurred_at", "wilayah", "jenis"}
    for secret in (SECRET_DESCRIPTION, SECRET_STREET, "Budi", "-7.77", "110.39", "00000000-0000", "11111111-1111", "Gang Mawar"):
        assert secret not in response.text, secret
    assert not (PRIVATE_KEYS & set(body["items"][0]))


def test_public_list_never_even_selects_private_columns_from_the_database():
    db = _use(FakeDb(reports=[_report(1)]))

    _list()

    [columns] = [e[2]["columns"] for e in db.log if e[0] == "reports" and e[1] == "select"]
    selected = {c.strip() for c in columns.split(",")}
    assert not ({"description", "jalan", "location_text", "id", "incident_id", "embedding"} & selected)


def test_public_list_hides_duplicate_and_hoax_flagged_reports_and_counts_only_visible_ones():
    _use(FakeDb(reports=[
        _report(1), _report(2, status="menunggu_verifikasi"),
        _report(3, status="ditandai_duplikat"), _report(4, status="ditandai_hoaks"),
    ]))

    body = _list().json()

    assert body["total"] == 2
    assert sorted(i["nomor"] for i in body["items"]) == ["GRD-000001", "GRD-000002"]
    assert {i["status"] for i in body["items"]} == {"terverifikasi", "menunggu_verifikasi"}


def test_public_list_is_newest_first_and_paginated_with_a_hard_cap():
    _use(FakeDb(reports=[_report(n) for n in range(1, 31)]))

    first = _list(limit=10).json()
    second = _list(limit=10, offset=10).json()
    capped = _list(limit=500).json()

    assert [i["nomor"] for i in first["items"]] == [f"GRD-{n:06d}" for n in range(30, 20, -1)]  # terbaru dulu
    assert [i["nomor"] for i in second["items"]][0] == "GRD-000020"
    assert first["total"] == 30 and first["limit"] == 10 and second["offset"] == 10
    assert capped["limit"] == get_settings().public_reports_max_page_size == 50 and len(capped["items"]) == 30
    assert _list(limit=0).status_code == 422 and _list(offset=-1).status_code == 422


def test_public_list_defaults_to_twenty_per_page():
    _use(FakeDb(reports=[_report(n) for n in range(1, 31)]))

    assert len(_list().json()["items"]) == 20


def test_public_time_is_floored_to_the_hour_in_wib_so_it_cannot_fingerprint_a_reporter():
    _use(FakeDb(reports=[_report(1, occurred_at="2026-10-20T15:47:31+00:00")]))  # 22:47 WIB

    item = _list().json()["items"][0]

    assert item["occurred_at"] == "2026-10-20T22:00:00+07:00"


def test_region_label_comes_from_kecamatan_code_or_nearest_kecamatan_for_legacy_reports():
    _use(FakeDb(reports=[
        _report(1, kecamatan_kode="34.71.02", latitude=None, longitude=None),  # dari kode
        _report(2, kecamatan_kode=None, latitude=-7.7701, longitude=110.3901),  # laporan lama: dari titik
        _report(3, kecamatan_kode=None, latitude=None, longitude=None),  # tak ada informasi lokasi
        _report(4, kecamatan_kode=None, latitude=-8.5, longitude=110.0),  # terlalu jauh dari kecamatan mana pun
    ]))

    labels = {i["nomor"]: i["wilayah"] for i in _list().json()["items"]}

    assert labels == {
        "GRD-000001": "Kec. Jetis, Kota Yogyakarta",
        "GRD-000002": "Kec. Depok, Kabupaten Sleman",
        "GRD-000003": "Daerah Istimewa Yogyakarta",
        "GRD-000004": "Daerah Istimewa Yogyakarta",
    }


def test_region_label_falls_back_when_the_area_directory_is_unavailable(monkeypatch):
    monkeypatch.setattr(reports_public, "get_directory_or_none", lambda _db: None)
    _use(FakeDb(reports=[_report(1)]))

    assert _list().json()["items"][0]["wilayah"] == "Daerah Istimewa Yogyakarta"


@pytest.mark.parametrize(
    ("extracted", "hint", "expected"),
    [
        ("penyerangan dengan senjata tajam", None, "penyerangan"),
        ("Klitih", None, "klitih"),
        (None, "begal/penodongan", "begal/penodongan"),  # Gemini gagal: pakai petunjuk dropdown
        ("percobaan begal", "pengrusakan", "begal/penodongan"),  # hasil Gemini diutamakan
        ("Korban luka-luka di bagian kepala", None, "lainnya"),  # rincian korban tidak ikut keluar
        (None, None, "lainnya"),
    ],
)
def test_incident_category_is_one_of_the_fixed_vocabulary_never_free_text(extracted, hint, expected):
    _use(FakeDb(reports=[_report(1, extracted_incident_type=extracted, incident_type_hint=hint)]))

    item = _list().json()["items"][0]

    assert item["jenis"] == expected
    assert "luka" not in item["jenis"]


def test_public_list_is_cached_and_the_cache_header_matches_the_setting():
    db = _use(FakeDb(reports=[_report(1)]))

    first = _list()
    db.rows("reports").append(_report(2))  # tidak terlihat selama cache berlaku
    second = _list()

    assert first.json() == second.json() and second.json()["total"] == 1
    assert len([e for e in db.log if e[1] == "select" and e[0] == "reports"]) == 1
    assert first.headers["cache-control"] == f"public, max-age={get_settings().public_reports_cache_seconds}"
    reports_public.clear_public_cache()
    assert _list().json()["total"] == 2


def test_database_failure_gives_a_safe_502_without_leaking_details(caplog):
    db = _use(FakeDb(reports=[_report(1)]))
    db.fail_on[("reports", "select")] = True

    with caplog.at_level(logging.DEBUG):
        response = _list()

    assert response.status_code == 502
    assert response.json()["detail"] == "Data laporan sementara tidak dapat diambil."
    assert "database mati" not in response.text and SECRET_DESCRIPTION not in caplog.text


def test_public_endpoints_are_rate_limited_per_ip(monkeypatch):
    monkeypatch.setenv("PUBLIC_REPORTS_RATE_LIMIT_MAX_REQUESTS", "3")
    get_settings.cache_clear()
    _use(FakeDb(reports=[_report(1)]))
    try:
        codes = [_list().status_code for _ in range(5)]
    finally:
        get_settings.cache_clear()

    assert codes == [200, 200, 200, 429, 429]


# ================================================================== statistik


def _incident(n, status="terverifikasi", seed=False):
    return {"id": f"i-{n}", "status": status, "is_seed_data": seed}


def test_stats_are_aggregate_numbers_only():
    _use(FakeDb(
        reports=[_report(1), _report(2), _report(3, status="menunggu_verifikasi"), _report(4, status="ditandai_duplikat"),
                 _report(5, status="ditandai_hoaks"), _report(6, status="ditandai_hoaks")],
        incidents=[_incident(1, seed=True), _incident(2, seed=True), _incident(3), _incident(4, status="baru")],
    ))

    response = client.get("/reports/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_reports": 6,
        "reports_by_status": {"menunggu_verifikasi": 1, "terverifikasi": 2, "ditandai_duplikat": 1, "ditandai_hoaks": 2},
        "verified_incidents": 3,
        "verified_incidents_from_reports": 1,
        "historical_incidents": 2,
    }
    for secret in (SECRET_DESCRIPTION, SECRET_STREET, "Budi"):
        assert secret not in response.text
    assert response.headers["cache-control"].startswith("public, max-age=")


def test_stats_are_cached_and_empty_database_gives_zeros():
    db = _use(FakeDb())
    empty = client.get("/reports/stats").json()
    db.rows("reports").append(_report(1))

    assert empty["total_reports"] == 0 and empty["verified_incidents"] == 0
    assert client.get("/reports/stats").json()["total_reports"] == 0  # masih dari cache
    reports_public.clear_public_cache()
    assert client.get("/reports/stats").json()["total_reports"] == 1


def test_stats_database_failure_is_a_safe_502():
    db = _use(FakeDb())
    db.fail_on[("incidents", "select")] = True

    response = client.get("/reports/stats")

    assert response.status_code == 502 and "database mati" not in response.text
