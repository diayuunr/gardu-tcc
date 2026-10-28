"""Penjaga: kolom `incidents.sumber` (URL/judul berita, bisa memuat ciri korban pada slug-nya) TIDAK PERNAH keluar dari
API publik maupun API moderasi. Dijaga di tiga lapis: skema OpenAPI, kode (kolom yang di-select), dan perilaku nyata
(respons endpoint yang memakai data insiden)."""

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from db_fake import FakeDb
from fastapi.testclient import TestClient
from route_helpers import point_at, road, route_of

from app.agents.incident_index import fetch_route_incidents, invalidate_incident_index
from app.agents.risk_agent import WIB, _fetch_scorable_incidents
from app.agents.route_agent import RouteAgentDeps
from app.api import reports_public
from app.api.route import get_route_agent_deps
from app.core import rate_limit
from app.core.areas import reset_area_directory_cache
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)
APP_DIR = Path(__file__).resolve().parent.parent / "app"
SECRET_URL = "https://www.detik.com/jateng/hukum-dan-kriminal/d-6016175/melihat-lebih-dekat-tkp-klithih-yang-tewaskan-anak-anggota-dprd"
SECRET_SOURCE = f"Detik.com — {SECRET_URL}. [PERKIRAAN] RAHASIA-SUMBER"
SECRET_TEXT = "RAHASIA-LOKASI-INSIDEN"
MOD_TOKEN = "jwt-moderator"


def _incident(ident, along_m=500.0, **extra):
    lat, lon = point_at(along_m)
    row = {
        "id": ident, "latitude": lat, "longitude": lon, "location_text": SECRET_TEXT, "sumber": SECRET_SOURCE,
        "incident_time": (datetime.now(WIB) - timedelta(days=5)).replace(hour=22, minute=0).isoformat(),
        "incident_type": "Penyerangan dengan celurit, korban tewas", "status": "terverifikasi", "is_seed_data": True,
    }
    row.update(extra)
    return row


def _db():
    incidents = [_incident(f"i{n}", along_m=400 + 30 * n) for n in range(6)]
    reports = [
        {"id": f"00000000-0000-4000-8000-{n:012d}", "public_number": n, "status": "terverifikasi", "incident_id": "i0",
         "description": "Deskripsi laporan warga tentang kejadian.", "location_text": "Kec. Depok, Kabupaten Sleman",
         "flagged_reason": None, "moderation_decision": None, "latitude": -7.77, "longitude": 110.39,
         "occurred_at": "2026-10-20T22:00:00+07:00", "created_at": f"2026-10-21T10:{n:02d}:00+00:00",
         "extracted_incident_type": "penyerangan", "incident_type_hint": None, "kecamatan_kode": None}
        for n in range(1, 4)
    ]
    return FakeDb(
        incidents=incidents, reports=reports,
        moderators=[{"id": "m1", "user_id": "u1", "display_name": "Mod"}], tokens={MOD_TOKEN: "u1"},
    )


@pytest.fixture(autouse=True)
def _clean():
    rate_limit._request_log.clear()
    reports_public.clear_public_cache()
    invalidate_incident_index()
    reset_area_directory_cache()
    yield
    for dependency in (get_supabase, get_route_agent_deps):
        app.dependency_overrides.pop(dependency, None)
    invalidate_incident_index()
    reset_area_directory_cache()
    reports_public.clear_public_cache()


# ---------------------------------------------------------------- lapis 1: skema


def _property_names(node) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        names |= set(node.get("properties", {}))
        for value in node.values():
            names |= _property_names(value)
    elif isinstance(node, list):
        for value in node:
            names |= _property_names(value)
    return names


def test_no_response_or_request_schema_in_the_whole_api_has_a_source_field():
    properties = _property_names(app.openapi())

    assert "sumber" not in properties and "source_url" not in properties and "sumber_url" not in properties


def test_the_only_source_field_is_the_search_layer_name_not_a_news_source():
    # `source` di /geo/search = asal data pencarian (landmark/photon/...), bukan sumber berita insiden.
    schema = app.openapi()["components"]["schemas"]["PlaceHitOut"]["properties"]["source"]
    assert set(schema["enum"]) == {"landmark", "photon", "nominatim", "wilayah", "mapbox"}
    holders = [name for name, body in app.openapi()["components"]["schemas"].items() if "source" in body.get("properties", {})]
    assert holders == ["PlaceHitOut"]


# ------------------------------------------------------------------ lapis 2: kode


def _select_strings(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "select":
            for arg in node.args[:1]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.append((node.lineno, arg.value))
                else:
                    found.append((node.lineno, "<dinamis>"))
            if not node.args:
                found.append((node.lineno, "*"))
    return found


def test_no_server_code_selects_the_source_column_or_everything_from_a_table():
    offenders = []
    for path in APP_DIR.rglob("*.py"):
        if "scripts" in path.parts:  # skrip CLI operator (seed_loader menulisnya; check_data memeriksanya) bukan API
            continue
        for line, columns in _select_strings(path):
            names = {c.strip() for c in columns.split(",")}
            if "sumber" in names or "*" in names:
                offenders.append(f"{path.relative_to(APP_DIR)}:{line} select({columns!r})")
    assert offenders == []


def test_the_scan_really_sees_selects_so_a_green_result_means_something():
    seen = [(p.name, c) for p in (APP_DIR / "agents").glob("*.py") for _l, c in _select_strings(p)]
    assert any("incident_time" in columns for _name, columns in seen)  # kolom insiden yang memang dipakai skor/rute


def test_the_columns_read_for_scoring_and_routes_never_include_the_source_column():
    db = _db()

    fetch_route_incidents(db)
    _fetch_scorable_incidents(db)

    requested = [e[2]["columns"] for e in db.log if e[0] == "incidents" and e[1] == "select"]
    assert len(requested) == 2 and all("sumber" not in c and "location_text" not in c for c in requested)


# ----------------------------------------------------------- lapis 3: perilaku


def _use(db):
    app.dependency_overrides[get_supabase] = lambda: db


def test_route_check_uses_incidents_that_have_a_source_yet_never_returns_it():
    db = _db()
    route = route_of(road("Jalan Uji", 0, 2000, 240, points=17))
    app.dependency_overrides[get_route_agent_deps] = lambda: RouteAgentDeps(
        supabase=db, fetch_route=lambda _o, _d: route, describe_area=lambda _la, _lo: None, narrate=lambda _f: None
    )
    departure = (datetime.now(WIB) + timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0, tzinfo=None)

    response = client.post("/route/check", json={
        "origin": {"latitude": point_at(0)[0], "longitude": point_at(0)[1]},
        "destination": {"latitude": point_at(2000)[0], "longitude": point_at(2000)[1]},
        "departure_time": departure.isoformat(),
    })

    assert response.status_code == 200, response.text
    assert any(s["incident_count"] > 0 for s in response.json()["segments"])  # insiden benar-benar dipakai
    for secret in (SECRET_URL, "RAHASIA-SUMBER", "detik.com", "anak-anggota-dprd", SECRET_TEXT, "korban tewas"):
        assert secret not in response.text, secret
    assert all("sumber" not in e[2]["columns"] for e in db.log if e[0] == "incidents" and e[1] == "select")


def test_public_report_endpoints_never_return_the_source_of_linked_incidents():
    db = _db()
    _use(db)

    for path in ("/reports/public", "/reports/stats"):
        response = client.get(path)
        assert response.status_code == 200
        for secret in (SECRET_URL, "RAHASIA-SUMBER", "detik.com", SECRET_TEXT):
            assert secret not in response.text, (path, secret)


def test_moderation_endpoints_never_return_the_source_of_linked_incidents():
    db = _db()
    _use(db)
    headers = {"Authorization": f"Bearer {MOD_TOKEN}"}

    listing = client.get("/moderation/reports", params={"status": "terverifikasi"}, headers=headers)
    decision = client.patch("/moderation/reports/00000000-0000-4000-8000-000000000001", json={"status": "terverifikasi"}, headers=headers)

    assert listing.status_code == 200 and listing.json()["total"] == 3 and decision.status_code == 200
    for response in (listing, decision):
        for secret in (SECRET_URL, "RAHASIA-SUMBER", "detik.com", SECRET_TEXT):
            assert secret not in response.text, secret
    # sinkronisasi insiden oleh keputusan moderator juga tidak membaca kolom sumber
    assert all("sumber" not in (e[2] or {}).get("columns", "") for e in db.log if e[1] == "select")
