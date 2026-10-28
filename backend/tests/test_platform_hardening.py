"""Tes Fase A: A1 dependensi, A3 deploy, A4 IP klien & rate limit, A5 CORS, A6 error handling,
timeout/retry, dan smoke test."""

import json
import logging
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.agents import embedding_service, verify_agent
from app.agents.risk_agent import locate_area
from app.agents.incident_index import IncidentIndex
from app.agents.route_agent import RouteAgentDeps
from app.api import geo as geo_api
from app.api import risk as risk_api
from app.api.route import get_route_agent_deps
from app.core import db_retry, rate_limit, supabase_client
from app.core.config import get_settings
from app.core.areas import reset_area_directory_cache
from app.core.places import PlaceHit, SearchResult
from app.core.cors import CorsConfigError, parse_cors_origins
from app.core.directions import RouteGeometry
from app.core.supabase_client import get_supabase
from app.main import app
from app.scripts.smoke_test import run_smoke

BACKEND = Path(__file__).resolve().parent.parent
client = TestClient(app)


def _set_env(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key.upper(), str(value))
    get_settings.cache_clear()


def _request(forwarded_for: str | None = None, peer: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (peer, 1234)})


# ================================================================ A1 + A3: dependensi & deploy


def test_requirements_pin_matches_the_pydantic_version_the_tests_run_on():
    pins = dict(
        line.split("==", 1) for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").split() if "==" in line
    )

    assert pins["pydantic"] == version("pydantic")  # pin lama (2.10.4) bentrok dengan supabase 2.31.0
    assert pins["supabase"] == version("supabase")


def test_railway_start_command_binds_to_port_and_trusts_proxy_headers():
    config = json.loads((BACKEND / "railpack.json").read_text(encoding="utf-8"))
    command = config["deploy"]["startCommand"]

    assert command.startswith("uvicorn app.main:app")
    for part in ("--host 0.0.0.0", "--port $PORT", "--proxy-headers", "--forwarded-allow-ips=*"):
        assert part in command
    assert (BACKEND / ".python-version").read_text(encoding="utf-8").strip() == "3.12"


# ======================================================================== A4: IP klien & limit


def test_forwarded_header_is_ignored_unless_proxy_headers_are_trusted():
    assert rate_limit._client_ip(_request("203.0.113.7")) == "10.0.0.9"  # klien tak bisa memalsukan IP


def test_leftmost_valid_forwarded_entry_is_used_when_proxy_is_trusted(monkeypatch):
    _set_env(monkeypatch, trust_proxy_headers="true")

    assert rate_limit._client_ip(_request("203.0.113.7, 10.1.1.1, 10.2.2.2")) == "203.0.113.7"
    assert rate_limit._client_ip(_request("tidak-valid, , 198.51.100.4:5555, 10.0.0.1")) == "198.51.100.4"
    assert rate_limit._client_ip(_request("2001:db8::1")) == "2001:db8::1"
    assert rate_limit._client_ip(_request("[2001:db8::2]:8080")) == "2001:db8::2"
    assert rate_limit._client_ip(_request("sampah, lagi-sampah")) == "10.0.0.9"  # tak ada yang valid -> alamat koneksi
    assert rate_limit._client_ip(_request(None)) == "10.0.0.9"  # tanpa header -> alamat koneksi


def test_spoofed_forwarded_headers_cannot_bypass_the_limit_without_a_trusted_proxy(monkeypatch):
    _set_env(monkeypatch, rate_limit_max_requests=2)

    rate_limit.enforce_rate_limit(_request("1.1.1.1"))
    rate_limit.enforce_rate_limit(_request("2.2.2.2"))
    with pytest.raises(HTTPException) as blocked:
        rate_limit.enforce_rate_limit(_request("3.3.3.3"))  # klien yang sama, header berganti-ganti

    assert blocked.value.status_code == 429


def test_trusted_proxy_gives_each_forwarded_client_its_own_bucket(monkeypatch):
    _set_env(monkeypatch, trust_proxy_headers="true", rate_limit_max_requests=1)

    rate_limit.enforce_rate_limit(_request("1.1.1.1"))
    rate_limit.enforce_rate_limit(_request("2.2.2.2"))  # klien lain di balik proxy yang sama: tidak terblokir
    with pytest.raises(HTTPException):
        rate_limit.enforce_rate_limit(_request("1.1.1.1"))


def test_ipv6_addresses_in_the_same_64_prefix_share_one_bucket(monkeypatch):
    _set_env(monkeypatch, trust_proxy_headers="true", rate_limit_max_requests=1)

    rate_limit.enforce_rate_limit(_request("2001:db8:1:2::1"))
    with pytest.raises(HTTPException):
        rate_limit.enforce_rate_limit(_request("2001:db8:1:2:ffff::9"))  # ganti alamat dalam /64 yang sama
    rate_limit.enforce_rate_limit(_request("2001:db8:1:3::1"))  # /64 lain


def test_raw_ip_is_never_stored_or_logged(monkeypatch, caplog):
    _set_env(monkeypatch, trust_proxy_headers="true", rate_limit_max_requests=1)

    with caplog.at_level(logging.DEBUG):
        rate_limit.enforce_rate_limit(_request("203.0.113.77"))
        with pytest.raises(HTTPException):
            rate_limit.enforce_rate_limit(_request("203.0.113.77"))

    assert rate_limit._request_log  # ada yang tercatat...
    assert all("203.0.113.77" not in key and "203" not in key.split(":")[-1][:3] for key in rate_limit._request_log)
    assert "203.0.113.77" not in caplog.text


def test_report_and_route_limits_are_separate_buckets_for_the_same_client(monkeypatch):
    _set_env(monkeypatch, rate_limit_max_requests=1, route_check_rate_limit_max_requests=1)

    rate_limit.enforce_rate_limit(_request())
    rate_limit.enforce_route_check_rate_limit(_request())  # jatah rute tidak habis oleh laporan
    with pytest.raises(HTTPException):
        rate_limit.enforce_route_check_rate_limit(_request())


def test_expired_buckets_are_purged_so_memory_cannot_grow_without_bound(monkeypatch):
    monkeypatch.setattr(rate_limit, "_PURGE_THRESHOLD", 3)
    monkeypatch.setattr(rate_limit, "_LONGEST_WINDOW_SECONDS", 0)
    for index in range(10):
        rate_limit._request_log[f"usang-{index}"].append(0.0)

    rate_limit.enforce_rate_limit(_request())

    assert len(rate_limit._request_log) <= 2


# ============================================================================ A5: CORS


def test_cors_origins_are_trimmed_deduplicated_and_empty_entries_ignored():
    assert parse_cors_origins(" https://a.app , ,http://localhost:3000/, https://a.app,") == [
        "https://a.app",
        "http://localhost:3000",
    ]


@pytest.mark.parametrize("raw", ["*", "https://a.app, *", " * ", "https://*.vercel.app"])
def test_wildcard_origins_are_rejected_because_credentials_are_enabled(raw):
    with pytest.raises(CorsConfigError, match="wildcard"):
        parse_cors_origins(raw)


@pytest.mark.parametrize("raw", ["", " , ,", "gardu.app", "ftp://gardu.app", "https://gardu.app/path"])
def test_empty_or_malformed_origin_lists_fail_fast_at_startup(raw):
    with pytest.raises(CorsConfigError):
        parse_cors_origins(raw)


def test_preflight_allows_configured_origin_and_not_others():
    allowed = client.options(
        "/reports", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    )
    denied = client.options(
        "/reports", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


# =========================================================== A6: penanganan error terpusat


def test_validation_errors_are_indonesian_and_never_echo_the_input():
    secret = "RAHASIA-ISI-LAPORAN"
    response = client.post("/reports", json={"description": secret[:5], "location_text": "x", "occurred_at": "bukan-waktu"})

    body = response.json()
    assert response.status_code == 422
    assert isinstance(body["detail"], str) and body["detail"].startswith("Input tidak valid")
    assert {e["field"] for e in body["errors"]} == {"description", "location_text", "occurred_at"}  # teks lokasi terlalu pendek
    assert "minimal 10 karakter" in body["detail"]
    assert secret[:5] not in response.text  # nilai yang dikirim pengguna tidak digemakan
    assert "String should" not in response.text and "Field required" not in response.text


def test_custom_validator_messages_pass_through_and_missing_fields_are_flagged():
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    body = client.post(
        "/reports", json={"description": "Ada kejadian mencurigakan di jalan", "location_text": "Kaliurang", "occurred_at": future}
    ).json()
    assert "tidak boleh di masa depan" in body["detail"]

    missing = client.post("/reports", json={}).json()
    assert {e["field"]: e["message"] for e in missing["errors"]} == {
        "description": "wajib diisi",
        "occurred_at": "wajib diisi",
    }


def test_query_parameter_errors_are_indonesian():
    not_a_number = client.get("/risk/score", params={"lat": "abc", "lon": 110}).json()
    bad_bucket = client.get("/risk/heatmap", params={"time_bucket": "tengah_malam"}).json()

    assert "Lintang: harus berupa angka" in not_a_number["detail"]
    assert "Rentang waktu: nilai tidak valid" in bad_bucket["detail"]
    assert "dini_hari" in bad_bucket["detail"]  # pilihan yang sah disebutkan


def test_404_and_405_use_indonesian_messages_but_custom_details_are_kept():
    assert client.get("/tidak-ada").json()["detail"] == "Alamat yang diminta tidak ditemukan."
    wrong_method = client.delete("/reports")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["detail"] == "Metode permintaan tidak diizinkan untuk alamat ini."
    assert "allow" in wrong_method.headers  # header bawaan Starlette tetap ada

    def custom(request: Request):
        raise HTTPException(status_code=429, detail="Pesan khusus dari endpoint.")

    app.dependency_overrides[rate_limit.enforce_rate_limit] = custom
    try:
        assert client.post("/reports", json={}).json()["detail"] == "Pesan khusus dari endpoint."
    finally:
        app.dependency_overrides.pop(rate_limit.enforce_rate_limit, None)


def test_unexpected_exception_becomes_a_generic_500_with_cors_headers_and_a_safe_log(caplog):
    def boom(request: Request):
        raise RuntimeError("gagal memproses RAHASIA-LAPORAN nomor hp 081234567890")

    app.dependency_overrides[rate_limit.enforce_rate_limit] = boom
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.post(
                "/reports?lat=-7.123456", json={}, headers={"Origin": "http://localhost:3000"}
            )
    finally:
        app.dependency_overrides.pop(rate_limit.enforce_rate_limit, None)

    assert response.status_code == 500
    assert response.json() == {"detail": "Terjadi kesalahan pada server, silakan coba lagi."}
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"  # browser tetap bisa membaca pesannya
    assert "RAHASIA-LAPORAN" not in response.text and "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert "7.123456" not in caplog.text  # query string (bisa berisi koordinat pengguna) tidak dicatat
    assert all(record.exc_info is None for record in caplog.records)
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)


# ========================================================== timeout & retry panggilan eksternal


def test_supabase_client_gets_a_finite_timeout_from_settings(monkeypatch):
    captured = {}
    monkeypatch.setattr(supabase_client, "create_client", lambda url, key, options: captured.update(options=options))
    _set_env(monkeypatch, supabase_timeout_seconds=3)
    supabase_client.get_supabase.cache_clear()
    try:
        supabase_client.get_supabase()
    finally:
        supabase_client.get_supabase.cache_clear()

    assert captured["options"].postgrest_client_timeout == 3.0  # bawaan library: 120 dtk


class _FlakyQuery:
    def __init__(self, error):
        self.error, self.calls = error, 0

    def execute(self):
        self.calls += 1
        if self.calls == 1:
            raise self.error
        return SimpleNamespace(data=["ok"])


@pytest.mark.parametrize(
    "error", [httpx.RemoteProtocolError("x"), httpx.ConnectError("x"), httpx.ConnectTimeout("x"), httpx.ReadError("x")]
)
def test_connection_level_failures_are_retried_once(monkeypatch, error):
    monkeypatch.setattr(db_retry.time, "sleep", lambda _s: None)
    query = _FlakyQuery(error)

    assert db_retry.execute_with_retry(query).data == ["ok"]
    assert query.calls == 2


def test_read_timeouts_and_database_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(db_retry.time, "sleep", lambda _s: None)
    for error in (httpx.ReadTimeout("x"), ValueError("x")):
        query = _FlakyQuery(error)
        with pytest.raises(type(error)):
            db_retry.execute_with_retry(query)
        assert query.calls == 1  # menggandakan waktu tunggu pengguna / mengulang kesalahan logika tak berguna


def test_embedding_and_extraction_calls_have_explicit_timeouts(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-not-real")
    _set_env(monkeypatch, gemini_timeout_seconds=7)
    seen = {}

    class _Embeddings:
        def __init__(self, **kwargs):
            seen["embeddings"] = kwargs

        def embed_query(self, _text, output_dimensionality=None):
            return [0.0] * embedding_service.EMBEDDING_DIMENSIONS

    class _Chat:
        def __init__(self, **kwargs):
            seen["chat"] = kwargs

        def with_structured_output(self, _schema):
            return SimpleNamespace(invoke=lambda _messages: None)

    monkeypatch.setattr(embedding_service, "GoogleGenerativeAIEmbeddings", _Embeddings)
    monkeypatch.setattr(verify_agent, "ChatGoogleGenerativeAI", _Chat)

    embedding_service.generate_embedding("teks")
    verify_agent._invoke_extraction("teks", "dummy-key-not-real")

    assert seen["embeddings"]["request_options"] == {"timeout": 7.0}
    assert seen["chat"]["timeout"] == 7.0 and seen["chat"]["max_retries"] == 1


# ================================================================================= smoke test


class _Db:
    """Supabase palsu: baris `risk_scores` dengan filter eq/in_ yang berperilaku nyata."""

    def __init__(self, rows, areas=None):
        self.rows, self.areas = rows, areas if areas is not None else []

    def table(self, name):
        return _DbQuery(self.areas if name == "areas" else self.rows)


class _DbQuery:
    def __init__(self, rows):
        self._rows, self._filters, self._limit, self._range = rows, [], None, None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append((column, {value}))
        return self

    def in_(self, column, values):
        self._filters.append((column, set(values)))
        return self

    def order(self, *_a):
        return self

    def limit(self, count):
        self._limit = count
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r[c] in v for c, v in self._filters)]
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=rows, count=len(rows))


def _score_rows():
    area = locate_area(-7.7956, 110.3695, 0.01)[2]
    return [
        {
            "area_name": area, "latitude": -7.795, "longitude": 110.365, "time_bucket": bucket, "risk_score": 4.0,
            "risk_level": "sedang", "contributing_incident_count": 2, "last_calculated_at": "2026-09-20T05:00:00+00:00",
            "place_name": "Kec. Gondokusuman", "kecamatan_kode": "34.71.03",
        }
        for bucket in ("dini_hari", "pagi", "siang", "sore", "malam")
    ]


def _area_rows():
    return [
        {"kode": "34.71", "nama": "Kota Yogyakarta", "tingkat": "kabkota", "parent_kode": None, "latitude": -7.7956, "longitude": 110.3695},
        {"kode": "34.71.03", "nama": "Gondokusuman", "tingkat": "kecamatan", "parent_kode": "34.71", "latitude": -7.78, "longitude": 110.38},
    ]


def _route_deps(db):
    route = RouteGeometry(
        points=((-7.812995, 110.39872), (-7.80, 110.38), (-7.783, 110.367)), distance_m=4800.0, duration_s=1260.0
    )
    return RouteAgentDeps(
        supabase=db,
        fetch_route=lambda _o, _d: route,
        describe_area=lambda _a, _b: None,
        incident_loader=lambda _supabase: IncidentIndex([]),
        directory_loader=lambda _supabase: None,
    )


@pytest.fixture
def healthy_backend(monkeypatch):
    monkeypatch.setattr(risk_api, "_heatmap_cache", {})  # cache global 60 dtk tidak boleh bocor antar test
    monkeypatch.setattr(risk_api, "_summary_cache", {})
    reset_area_directory_cache()
    monkeypatch.setattr(
        geo_api.places,
        "search",
        lambda _q, _limit, _directory=None: SearchResult(
            (PlaceHit("Tugu Yogyakarta", "Tugu Yogyakarta, DIY", -7.783, 110.367, source="landmark"),), degraded=False
        ),
    )
    db = _Db(_score_rows(), _area_rows())
    app.dependency_overrides[get_supabase] = lambda: db
    app.dependency_overrides[get_route_agent_deps] = lambda: _route_deps(db)
    yield
    app.dependency_overrides.pop(get_supabase, None)
    app.dependency_overrides.pop(get_route_agent_deps, None)


def test_smoke_test_passes_against_a_healthy_backend(healthy_backend):
    results = run_smoke(TestClient(app), origin="http://localhost:3000")

    assert [r.name for r in results if not r.ok] == []
    assert len(results) >= 16  # termasuk /areas, /risk/summary, /geo/reverse, /geo/search


def test_smoke_test_reports_failures_instead_of_hiding_them(healthy_backend):
    class _Down:
        def table(self, _name):
            raise RuntimeError("db down")

    app.dependency_overrides[get_supabase] = lambda: _Down()
    results = run_smoke(TestClient(app), origin="https://evil.example")

    failed = {r.name for r in results if not r.ok}
    assert "GET /health (termasuk database)" in failed
    assert "GET /risk/heatmap" in failed
    assert any(name.startswith("CORS preflight") for name in failed)
    assert "Tidak ada kebocoran detail internal di respons" not in failed  # gagal rapi tanpa bocor


def test_smoke_test_flags_a_leaking_response():
    def leaky_transport(request):
        return httpx.Response(500, text='Traceback (most recent call last):\n  File "x.py"')

    leaky = httpx.Client(transport=httpx.MockTransport(leaky_transport), base_url="http://testserver")
    results = run_smoke(leaky)

    assert next(r for r in results if r.name.startswith("Tidak ada kebocoran")).ok is False
