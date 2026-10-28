"""Fase E3/E4: /internal/reprocess dan /internal/recalculate-risk — dilindungi token rahasia, berjalan di latar belakang."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.agents.reprocess import ReprocessSummary
from app.api import internal as internal_api
from app.core import rate_limit
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)
TOKEN = "token-internal-rahasia-yang-cukup-panjang-123456"
HEADERS = {"X-Internal-Token": TOKEN}


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_TOKEN", TOKEN)
    get_settings.cache_clear()
    rate_limit._request_log.clear()
    app.dependency_overrides[get_supabase] = lambda: object()
    if internal_api._reprocess_lock.locked():  # test lain tak boleh mewarisi kunci yang tersangkut
        internal_api._reprocess_lock.release()
    yield
    app.dependency_overrides.pop(get_supabase, None)
    rate_limit._request_log.clear()
    get_settings.cache_clear()


@pytest.fixture
def jobs(monkeypatch):
    """Ganti pencarian & pemrosesan laporan dengan perekam; kembalikan catatan panggilan."""
    record = {"found": ["r1", "r2", "r3"], "finds": [], "runs": [], "refresh": [], "fail_run": False}

    def find(_db, limit, _older_than):
        record["finds"].append(limit)
        return record["found"][:limit]

    def run(_db, *, dry_run, limit, delay_seconds, min_age_minutes, **_kw):
        if record["fail_run"]:
            raise RuntimeError("Gemini mati (simulasi)")
        record["runs"].append({"limit": limit, "dry_run": dry_run, "delay": delay_seconds, "min_age": min_age_minutes})
        return ReprocessSummary(tuple(record["found"][:limit]), processed=len(record["found"][:limit]), dry_run=False)

    monkeypatch.setattr(internal_api, "find_unfinished_reports", find)
    monkeypatch.setattr(internal_api, "reprocess_reports", run)
    monkeypatch.setattr(internal_api, "refresh_risk_scores_safely", lambda: record["refresh"].append("x"))
    return record


# ============================================================= perlindungan token


@pytest.mark.parametrize("path", ["/internal/reprocess", "/internal/recalculate-risk"])
def test_endpoints_are_disabled_with_404_when_no_token_is_configured(monkeypatch, path, jobs):
    monkeypatch.setenv("INTERNAL_API_TOKEN", "")
    get_settings.cache_clear()

    for headers in ({}, HEADERS, {"X-Internal-Token": ""}):
        assert client.post(path, headers=headers).status_code == 404
    assert jobs["runs"] == [] and jobs["refresh"] == []


@pytest.mark.parametrize("path", ["/internal/reprocess", "/internal/recalculate-risk"])
@pytest.mark.parametrize("headers", [
    {}, {"X-Internal-Token": ""}, {"X-Internal-Token": "salah"}, {"X-Internal-Token": TOKEN + "x"},
    {"X-Internal-Token": TOKEN[:-1]}, {"X-Internal-Token": TOKEN.upper()}, {"Authorization": f"Bearer {TOKEN}"},
])
def test_missing_or_wrong_token_is_401_and_nothing_runs(path, headers, jobs):
    response = client.post(path, headers=headers)

    assert response.status_code == 401
    assert TOKEN not in response.text
    assert jobs["finds"] == [] and jobs["runs"] == [] and jobs["refresh"] == []


def test_the_token_comparison_is_constant_time(monkeypatch, jobs):
    used = []
    real = internal_api.require_internal_token.__globals__["hmac"].compare_digest
    monkeypatch.setattr("app.core.auth.hmac.compare_digest", lambda a, b: (used.append(True), real(a, b))[1])

    client.post("/internal/recalculate-risk", headers=HEADERS)

    assert used == [True]


def test_token_guessing_is_rate_limited(monkeypatch, jobs):
    monkeypatch.setenv("INTERNAL_RATE_LIMIT_MAX_REQUESTS", "3")
    get_settings.cache_clear()

    codes = [client.post("/internal/recalculate-risk", headers={"X-Internal-Token": f"tebakan{n}"}).status_code for n in range(5)]

    assert codes == [401, 401, 401, 429, 429]


def test_the_token_never_appears_in_logs(caplog, jobs):
    with caplog.at_level(logging.DEBUG):
        client.post("/internal/reprocess", headers=HEADERS)
        client.post("/internal/reprocess", headers={"X-Internal-Token": "salah-tapi-rahasia"})

    assert TOKEN not in caplog.text and "salah-tapi-rahasia" not in caplog.text


# ================================================================== reprocess


def test_reprocess_queues_the_orphan_reports_and_runs_them_in_the_background(jobs):
    response = client.post("/internal/reprocess", headers=HEADERS)

    assert response.status_code == 202
    assert response.json() == {"found": 3, "queued": 3, "dry_run": False}
    settings = get_settings()
    assert jobs["runs"] == [{"limit": 20, "dry_run": False, "delay": settings.reprocess_delay_seconds,
                             "min_age": settings.reprocess_min_age_minutes}]
    assert not internal_api._reprocess_lock.locked()  # kunci dilepas setelah selesai


def test_reprocess_dry_run_only_counts(jobs):
    response = client.post("/internal/reprocess", params={"dry_run": "true"}, headers=HEADERS)

    assert response.status_code == 202 and response.json() == {"found": 3, "queued": 0, "dry_run": True}
    assert jobs["runs"] == []


def test_reprocess_batch_is_capped_by_the_configured_maximum(monkeypatch, jobs):
    monkeypatch.setenv("INTERNAL_REPROCESS_MAX_BATCH", "2")
    get_settings.cache_clear()

    body = client.post("/internal/reprocess", params={"limit": 500}, headers=HEADERS).json()

    assert body["found"] == 2 and jobs["finds"] == [2] and jobs["runs"][0]["limit"] == 2
    assert client.post("/internal/reprocess", params={"limit": 0}, headers=HEADERS).status_code == 422


def test_reprocess_with_nothing_to_do_does_not_start_a_job(jobs):
    jobs["found"] = []

    response = client.post("/internal/reprocess", headers=HEADERS)

    assert response.json() == {"found": 0, "queued": 0, "dry_run": False} and jobs["runs"] == []


def test_a_second_reprocess_while_one_is_running_gets_409(jobs):
    assert internal_api._reprocess_lock.acquire(blocking=False)  # simulasi proses ulang yang sedang berjalan

    response = client.post("/internal/reprocess", headers=HEADERS)

    assert response.status_code == 409 and jobs["runs"] == []
    assert internal_api._reprocess_lock.locked()  # kunci milik proses lain tidak dilepas oleh penolakan ini


def test_a_failing_job_releases_the_lock_and_never_leaks_details(caplog, jobs):
    jobs["fail_run"] = True

    with caplog.at_level(logging.DEBUG):
        response = client.post("/internal/reprocess", headers=HEADERS)

    assert response.status_code == 202
    assert not internal_api._reprocess_lock.locked()  # panggilan berikutnya tidak terkunci selamanya
    assert "Gemini mati" not in caplog.text
    jobs["fail_run"] = False
    assert client.post("/internal/reprocess", headers=HEADERS).status_code == 202


def test_database_failure_while_looking_for_orphans_is_a_safe_502(monkeypatch, jobs):
    def broken(*_a):
        raise RuntimeError("database mati (simulasi)")

    monkeypatch.setattr(internal_api, "find_unfinished_reports", broken)

    response = client.post("/internal/reprocess", headers=HEADERS)

    assert response.status_code == 502 and "database mati" not in response.text
    assert not internal_api._reprocess_lock.locked()


# ============================================================== recalculate-risk


def test_recalculate_risk_is_accepted_and_triggers_the_coalescing_refresh_once(jobs):
    response = client.post("/internal/recalculate-risk", headers=HEADERS)

    assert response.status_code == 202 and response.json() == {"accepted": True}
    assert jobs["refresh"] == ["x"]


def test_internal_endpoints_are_post_only(jobs):
    assert client.get("/internal/reprocess", headers=HEADERS).status_code == 405
    assert client.get("/internal/recalculate-risk", headers=HEADERS).status_code == 405
