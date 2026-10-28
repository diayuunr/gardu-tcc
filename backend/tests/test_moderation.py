"""Fase E2: /moderation/* — JWT Supabase Auth + tabel moderators, antrean, dan keputusan beserta sinkronisasi insiden."""

import logging
import uuid

import pytest
from db_fake import FakeDb
from fastapi.testclient import TestClient

from app.api import moderation as moderation_api
from app.core import rate_limit
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)

MOD_ID = "aaaaaaaa-0000-4000-8000-000000000001"
MOD_USER = "bbbbbbbb-0000-4000-8000-000000000001"
GOOD_TOKEN = "jwt-moderator-valid-RAHASIA"
OUTSIDER_TOKEN = "jwt-pengguna-biasa"
AUTH = {"Authorization": f"Bearer {GOOD_TOKEN}"}


def _uid() -> str:
    return str(uuid.uuid4())


def _report(**overrides):
    row = {
        "id": _uid(), "public_number": 1, "status": "menunggu_verifikasi", "flagged_reason": None,
        "moderation_decision": None, "description": "Ada kelompok remaja membawa senjata tajam di perempatan.",
        "location_text": "Kec. Depok, Kabupaten Sleman", "latitude": -7.77, "longitude": 110.39,
        "occurred_at": "2026-10-20T22:00:00+07:00", "created_at": "2026-10-21T10:00:00+00:00",
        "extracted_incident_type": "penyerangan", "incident_type_hint": None, "incident_id": None,
    }
    row.update(overrides)
    return row


def _incident(status="baru", seed=False, **overrides):
    row = {"id": _uid(), "status": status, "is_seed_data": seed, "location_text": "Depok", "latitude": -7.77,
           "longitude": 110.39, "incident_time": "2026-10-20T22:00:00+07:00", "incident_type": "penyerangan"}
    row.update(overrides)
    return row


def _db(reports=(), incidents=()):
    return FakeDb(
        reports=list(reports), incidents=list(incidents),
        moderators=[{"id": MOD_ID, "user_id": MOD_USER, "display_name": "Mod Satu"}],
        tokens={GOOD_TOKEN: MOD_USER, OUTSIDER_TOKEN: "cccccccc-0000-4000-8000-000000000009"},
    )


@pytest.fixture
def refreshes(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(moderation_api, "refresh_risk_scores_safely", lambda: calls.append("refresh"))
    return calls


@pytest.fixture(autouse=True)
def _clean():
    rate_limit._request_log.clear()
    yield
    app.dependency_overrides.pop(get_supabase, None)
    rate_limit._request_log.clear()


def _use(db):
    app.dependency_overrides[get_supabase] = lambda: db
    return db


def _patch(report_id, status, headers=AUTH):
    return client.patch(f"/moderation/reports/{report_id}", json={"status": status}, headers=headers)


# ================================================================ autentikasi


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer "},
    {"Authorization": f"Basic {GOOD_TOKEN}"}, {"Authorization": GOOD_TOKEN}, {"Authorization": "Bearer " + "x" * 5000},
])
def test_requests_without_a_proper_bearer_token_are_401_on_every_endpoint(headers):
    _use(_db([_report()]))
    rid = _uid()

    assert client.get("/moderation/me", headers=headers).status_code == 401
    assert client.get("/moderation/reports", headers=headers).status_code == 401
    assert client.patch(f"/moderation/reports/{rid}", json={"status": "terverifikasi"}, headers=headers).status_code == 401


def test_invalid_expired_or_forged_tokens_are_401_and_the_response_has_a_bearer_challenge():
    _use(_db([_report()]))

    response = client.get("/moderation/me", headers={"Authorization": "Bearer token-palsu"})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "token-palsu" not in response.text


def test_a_valid_user_who_is_not_in_the_moderators_table_gets_403_and_changes_nothing():
    db = _use(_db([_report()]))
    outsider = {"Authorization": f"Bearer {OUTSIDER_TOKEN}"}

    assert client.get("/moderation/me", headers=outsider).status_code == 403
    assert client.get("/moderation/reports", headers=outsider).status_code == 403
    assert _patch(db.rows("reports")[0]["id"], "terverifikasi", outsider).status_code == 403
    assert db.writes() == []


def test_a_registered_moderator_passes_and_sees_their_display_name():
    _use(_db())

    response = client.get("/moderation/me", headers=AUTH)

    assert response.status_code == 200 and response.json() == {"display_name": "Mod Satu"}


def test_supabase_auth_outage_is_503_not_401_and_never_logs_the_token(caplog):
    db = _use(_db())
    db.auth.down = True

    with caplog.at_level(logging.DEBUG):
        response = client.get("/moderation/me", headers=AUTH)

    assert response.status_code == 503
    assert GOOD_TOKEN not in caplog.text and GOOD_TOKEN not in response.text


def test_the_token_is_verified_against_supabase_not_merely_decoded():
    class Spy(FakeDb):
        pass

    db = _use(_db())
    seen = []
    original = db.auth.get_user
    db.auth.get_user = lambda token: (seen.append(token), original(token))[1]

    client.get("/moderation/me", headers={"Authorization": "bearer " + GOOD_TOKEN})  # skema tak peka huruf besar

    assert seen == [GOOD_TOKEN]


def test_moderation_is_rate_limited_before_the_token_is_even_checked(monkeypatch):
    monkeypatch.setenv("MODERATION_RATE_LIMIT_MAX_REQUESTS", "3")
    get_settings.cache_clear()
    _use(_db())
    try:
        codes = [client.get("/moderation/me", headers={"Authorization": "Bearer tebakan"}).status_code for _ in range(5)]
    finally:
        get_settings.cache_clear()

    assert codes == [401, 401, 401, 429, 429]


# ===================================================================== antrean


def test_default_queue_has_everything_needing_review_but_not_verified_reports():
    _use(_db([
        _report(public_number=1, status="menunggu_verifikasi"),
        _report(public_number=2, status="ditandai_duplikat", flagged_reason="mirip_laporan_lain"),
        _report(public_number=3, status="ditandai_hoaks", flagged_reason="karakter_berulang"),
        _report(public_number=4, status="terverifikasi"),
    ]))

    body = client.get("/moderation/reports", headers=AUTH).json()

    assert body["total"] == 3 and sorted(i["nomor"] for i in body["items"]) == ["GRD-000001", "GRD-000002", "GRD-000003"]
    flagged = {i["nomor"]: i["flagged_reason"] for i in body["items"]}
    assert flagged["GRD-000002"] == "mirip_laporan_lain" and flagged["GRD-000003"] == "karakter_berulang"


def test_queue_can_be_filtered_by_one_or_more_statuses_and_paginated():
    _use(_db([_report(public_number=n, status="terverifikasi", created_at=f"2026-10-21T10:{n:02d}:00+00:00") for n in range(1, 8)]
             + [_report(public_number=20, status="ditandai_hoaks")]))

    only_verified = client.get("/moderation/reports", params={"status": "terverifikasi", "limit": 3}, headers=AUTH).json()
    both = client.get("/moderation/reports", params=[("status", "terverifikasi"), ("status", "ditandai_hoaks")], headers=AUTH).json()

    assert only_verified["total"] == 7 and [i["nomor"] for i in only_verified["items"]] == ["GRD-000007", "GRD-000006", "GRD-000005"]
    assert both["total"] == 8
    assert client.get("/moderation/reports", params={"status": "bukan-status"}, headers=AUTH).status_code == 422
    assert client.get("/moderation/reports", params={"limit": 0}, headers=AUTH).status_code == 422
    assert client.get("/moderation/reports", params={"limit": 9999}, headers=AUTH).json()["limit"] == 100


def test_moderators_see_the_content_but_never_coordinates():
    _use(_db([_report(public_number=5, incident_type_hint="klitih")]))

    [item] = client.get("/moderation/reports", headers=AUTH).json()["items"]

    assert item["description"].startswith("Ada kelompok remaja") and item["location_text"] == "Kec. Depok, Kabupaten Sleman"
    assert item["incident_type_hint"] == "klitih" and item["extracted_incident_type"] == "penyerangan"
    assert not ({"latitude", "longitude", "embedding"} & set(item))


# ===================================================================== keputusan


def test_approving_a_lone_pending_report_verifies_its_incident_and_refreshes_scores(refreshes):
    incident = _incident()
    report = _report(incident_id=incident["id"])
    db = _use(_db([report], [incident]))

    response = _patch(report["id"], "terverifikasi")

    assert response.status_code == 200
    assert response.json() == {"id": report["id"], "status": "terverifikasi", "changed": True,
                               "incident_status": "terverifikasi", "scores_refresh_scheduled": True}
    saved = db.row("reports", report["id"])
    assert saved["status"] == "terverifikasi" and saved["moderation_decision"] == "disetujui"
    assert saved["moderated_by"] == MOD_ID and saved["moderated_at"]
    assert db.row("incidents", incident["id"])["status"] == "terverifikasi"
    assert refreshes == ["refresh"]


def test_approving_a_flagged_report_without_an_incident_creates_one_from_it_using_the_hint(refreshes):
    report = _report(status="ditandai_hoaks", flagged_reason="karakter_berulang", moderation_decision=None,
                     extracted_incident_type=None, incident_type_hint="begal/penodongan")
    db = _use(_db([report]))

    response = _patch(report["id"], "terverifikasi")

    assert response.json()["incident_status"] == "terverifikasi"
    [created] = db.rows("incidents")
    assert created["incident_type"] == "begal/penodongan" and created["status"] == "terverifikasi" and created["is_seed_data"] is False
    saved = db.row("reports", report["id"])
    assert saved["incident_id"] == created["id"] and saved["flagged_reason"] is None
    assert refreshes == ["refresh"]


def test_rejecting_one_of_two_reports_detaches_it_and_demotes_the_incident(refreshes):
    incident = _incident(status="terverifikasi")
    keep = _report(incident_id=incident["id"], status="terverifikasi", public_number=1)
    reject = _report(incident_id=incident["id"], status="terverifikasi", public_number=2)
    db = _use(_db([keep, reject], [incident]))

    response = _patch(reject["id"], "ditandai_hoaks")

    assert response.json()["incident_status"] is None  # laporan yang ditolak sudah tidak terhubung ke insiden
    assert response.json()["scores_refresh_scheduled"] is True
    rejected = db.row("reports", reject["id"])
    assert rejected["status"] == "ditandai_hoaks" and rejected["moderation_decision"] == "ditolak"
    assert rejected["incident_id"] is None and rejected["flagged_reason"] == "ditolak_moderator"  # invarian: ditandai tak punya insiden
    assert db.row("reports", keep["id"])["status"] == "menunggu_verifikasi"  # promosi otomatisnya ikut dicabut
    assert db.row("incidents", incident["id"])["status"] == "baru"
    assert refreshes == ["refresh"]


def test_rejecting_one_of_three_keeps_the_incident_verified_and_does_not_refresh(refreshes):
    incident = _incident(status="terverifikasi")
    reports = [_report(incident_id=incident["id"], status="terverifikasi", public_number=n) for n in (1, 2, 3)]
    db = _use(_db(reports, [incident]))

    response = _patch(reports[2]["id"], "ditandai_hoaks")

    assert response.json()["incident_status"] is None and response.json()["scores_refresh_scheduled"] is False
    assert db.row("incidents", incident["id"])["status"] == "terverifikasi"
    assert [r["status"] for r in db.rows("reports")[:2]] == ["terverifikasi", "terverifikasi"]
    assert refreshes == []


def test_a_moderator_approved_report_keeps_the_incident_verified_even_when_its_partner_is_rejected(refreshes):
    incident = _incident(status="terverifikasi")
    approved = _report(incident_id=incident["id"], status="terverifikasi", moderation_decision="disetujui", public_number=1)
    other = _report(incident_id=incident["id"], status="terverifikasi", public_number=2)
    db = _use(_db([approved, other], [incident]))

    response = _patch(other["id"], "ditandai_hoaks")

    assert response.json()["incident_status"] is None and refreshes == []
    assert db.row("reports", approved["id"])["status"] == "terverifikasi"
    assert db.row("incidents", incident["id"])["status"] == "terverifikasi"


def test_rejecting_the_only_report_deletes_the_community_incident(refreshes):
    incident = _incident(status="baru")
    report = _report(incident_id=incident["id"])
    db = _use(_db([report], [incident]))

    response = _patch(report["id"], "ditandai_hoaks")

    assert response.json()["incident_status"] is None
    assert db.rows("incidents") == [] and refreshes == []  # insiden 'baru' tak pernah ikut skor -> tak perlu hitung ulang


def test_rejecting_the_only_report_of_a_verified_incident_deletes_it_and_refreshes_scores(refreshes):
    incident = _incident(status="terverifikasi")
    report = _report(incident_id=incident["id"], status="terverifikasi", moderation_decision="disetujui")
    db = _use(_db([report], [incident]))

    _patch(report["id"], "ditandai_hoaks")

    assert db.rows("incidents") == [] and refreshes == ["refresh"]


def test_returning_a_verified_report_to_waiting_detaches_it_so_it_can_be_reclustered(refreshes):
    incident = _incident(status="terverifikasi")
    report = _report(incident_id=incident["id"], status="terverifikasi", moderation_decision="disetujui")
    db = _use(_db([report], [incident]))

    response = _patch(report["id"], "menunggu_verifikasi")

    saved = db.row("reports", report["id"])
    assert response.json()["status"] == "menunggu_verifikasi"
    assert saved["status"] == "menunggu_verifikasi" and saved["moderation_decision"] is None and saved["incident_id"] is None
    assert db.rows("incidents") == [] and refreshes == ["refresh"]


def test_returning_a_flagged_report_to_waiting_clears_the_flag():
    report = _report(status="ditandai_duplikat", flagged_reason="mirip_laporan_lain")
    db = _use(_db([report]))

    _patch(report["id"], "menunggu_verifikasi")

    saved = db.row("reports", report["id"])
    assert saved["status"] == "menunggu_verifikasi" and saved["flagged_reason"] is None


def test_approving_an_auto_verified_member_records_the_human_decision_without_changing_the_incident(refreshes):
    incident = _incident(status="terverifikasi")
    reports = [_report(incident_id=incident["id"], status="terverifikasi", public_number=n) for n in (1, 2)]
    db = _use(_db(reports, [incident]))

    response = _patch(reports[0]["id"], "terverifikasi")

    assert response.json()["changed"] is True and response.json()["scores_refresh_scheduled"] is False
    assert db.row("reports", reports[0]["id"])["moderation_decision"] == "disetujui" and refreshes == []


def test_repeating_the_same_decision_is_idempotent_and_writes_nothing_to_reports(refreshes):
    incident = _incident(status="terverifikasi")
    report = _report(incident_id=incident["id"], status="terverifikasi", moderation_decision="disetujui")
    db = _use(_db([report], [incident]))

    response = _patch(report["id"], "terverifikasi")

    assert response.json()["changed"] is False and response.json()["incident_status"] == "terverifikasi"
    assert db.writes("reports") == [] and refreshes == []


def test_repeating_a_rejection_of_an_already_detached_report_is_a_harmless_noop(refreshes):
    incident = _incident(status="terverifikasi")
    survivor = _report(incident_id=incident["id"], status="terverifikasi", public_number=1)
    rejected = _report(status="ditandai_hoaks", moderation_decision="ditolak", incident_id=None, public_number=2)
    db = _use(_db([survivor, rejected], [incident]))

    response = _patch(rejected["id"], "ditandai_hoaks")

    assert response.json()["changed"] is False and response.json()["incident_status"] is None
    assert db.writes() == [] and refreshes == []


def test_seed_data_incidents_are_never_touched_by_a_decision(refreshes):
    seed = _incident(status="terverifikasi", seed=True)
    report = _report(incident_id=seed["id"], status="terverifikasi")
    db = _use(_db([report], [seed]))

    response = _patch(report["id"], "ditandai_hoaks")

    assert response.status_code == 200 and refreshes == []
    assert db.row("incidents", seed["id"])["status"] == "terverifikasi" and len(db.rows("incidents")) == 1
    assert db.writes("incidents") == []


def test_unknown_report_is_404_and_a_bad_id_or_status_is_422():
    _use(_db([_report()]))

    assert _patch(_uid(), "terverifikasi").status_code == 404
    assert client.patch("/moderation/reports/bukan-uuid", json={"status": "terverifikasi"}, headers=AUTH).status_code == 422
    for bad in ("ditandai_duplikat", "baru", ""):
        assert _patch(_uid(), bad).status_code == 422
    assert client.patch(f"/moderation/reports/{_uid()}", json={}, headers=AUTH).status_code == 422


def test_database_failure_during_a_decision_is_a_safe_502(caplog):
    report = _report()
    db = _use(_db([report]))
    db.fail_on[("reports", "update")] = True

    with caplog.at_level(logging.DEBUG):
        response = _patch(report["id"], "terverifikasi")

    assert response.status_code == 502 and "database mati" not in response.text
    assert report["description"] not in caplog.text and GOOD_TOKEN not in caplog.text


def test_decisions_are_logged_by_ids_only(caplog, refreshes):
    report = _report()
    _use(_db([report]))

    with caplog.at_level(logging.INFO):
        _patch(report["id"], "ditandai_hoaks")

    assert report["id"] in caplog.text and MOD_ID in caplog.text
    assert report["description"] not in caplog.text and GOOD_TOKEN not in caplog.text
