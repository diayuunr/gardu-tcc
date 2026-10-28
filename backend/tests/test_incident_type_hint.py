"""Fase E5: `incident_type_hint` — kategori dari dropdown, disimpan terpisah, dipakai bila ekstraksi Gemini gagal."""

import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_verify_clustering import CLEAN_TEXT, _FakeSupabase, _report, _run

import app.api.reports as reports_module
from app.agents import verify_agent
from app.agents.incident_index import CATEGORY_OTHER, CATEGORY_RULES, normalize_category
from app.core.supabase_client import get_supabase
from app.main import app
from app.schemas.report import IncidentTypeHint, ReportCreate

MIGRATION = Path(__file__).resolve().parent.parent / "supabase" / "migrations" / "20260924000000_reports_public_moderation.sql"
NOW = datetime.now() - timedelta(hours=2)


def _create(**extra):
    return ReportCreate(description=CLEAN_TEXT, location_text="Kaliurang", occurred_at=NOW, **extra)


# ------------------------------------------------------------------ skema


def test_hint_is_optional_and_accepts_every_dropdown_category():
    assert _create().incident_type_hint is None
    for value in get_args(IncidentTypeHint):
        assert _create(incident_type_hint=value).incident_type_hint == value


@pytest.mark.parametrize("bad", ["Klitih", "bebas diisi sendiri", "", "penyerangan; DROP TABLE reports", "x" * 300])
def test_hint_rejects_anything_outside_the_fixed_vocabulary(bad):
    with pytest.raises(ValidationError):
        _create(incident_type_hint=bad)


def test_hint_vocabulary_matches_the_incident_categories_and_the_database_check():
    categories = {name for name, _pattern in CATEGORY_RULES} | {CATEGORY_OTHER}
    assert set(get_args(IncidentTypeHint)) == categories
    sql = MIGRATION.read_text(encoding="utf-8")
    in_check = set(re.findall(r"'([^']+)'", sql[sql.index("reports_incident_type_hint_valid") :].split(");")[0]))
    assert in_check == categories
    for value in get_args(IncidentTypeHint):
        assert normalize_category(value) == value  # kategori tidak berubah saat dinormalisasi untuk tampilan publik


def test_hint_is_never_merged_into_the_description_so_embeddings_stay_clean():
    report = _create(incident_type_hint="klitih")

    assert report.description == CLEAN_TEXT and "klitih" not in report.description.lower()


# --------------------------------------------------------------- endpoint


def _post(monkeypatch, **extra):
    saved: list[dict] = []

    class _Table:
        def insert(self, record):
            saved.append(record)
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": "r-1", "status": "menunggu_verifikasi", "created_at": "2026-09-20T00:00:00+00:00"}])

    monkeypatch.setattr(reports_module, "process_report_verification", lambda _id: None)
    app.dependency_overrides[get_supabase] = lambda: SimpleNamespace(table=lambda _n: _Table())
    try:
        response = TestClient(app).post(
            "/reports",
            json={"description": CLEAN_TEXT, "location_text": "Kaliurang", "occurred_at": NOW.isoformat(), **extra},
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)
    return response, saved


def test_submit_stores_the_hint_in_its_own_column_and_leaves_the_description_untouched(monkeypatch):
    response, saved = _post(monkeypatch, incident_type_hint="begal/penodongan")

    assert response.status_code == 201
    assert saved[0]["incident_type_hint"] == "begal/penodongan" and saved[0]["description"] == CLEAN_TEXT


def test_submit_without_a_hint_does_not_send_the_column_so_old_databases_still_work(monkeypatch):
    response, saved = _post(monkeypatch)

    assert response.status_code == 201 and "incident_type_hint" not in saved[0]


def test_submit_rejects_an_unknown_hint_with_422(monkeypatch):
    response, saved = _post(monkeypatch, incident_type_hint="apa saja")

    assert response.status_code == 422 and saved == []


# ----------------------------------------------------------- verifikasi


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _d: [0.1] * 768)
    monkeypatch.setattr(verify_agent, "refresh_risk_scores_safely", lambda: None)


def test_gemini_failure_falls_back_to_the_hint_for_the_incident_but_not_for_the_extracted_column(monkeypatch, stubs):
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: None)  # Gemini mati
    report = _report(incident_type_hint="pengrusakan")
    fake = _FakeSupabase([report])

    _run(monkeypatch, fake, report)

    [incident] = fake.incidents
    assert incident["incident_type"] == "pengrusakan"
    assert fake.reports[0]["incident_id"] == incident["id"]
    assert fake.reports[0]["extracted_incident_type"] is None  # petunjuk bukan hasil ekstraksi: proses ulang tetap mencoba Gemini


def test_gemini_result_wins_over_the_hint_and_is_saved(monkeypatch, stubs):
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: "penyerangan")
    report = _report(incident_type_hint="pengrusakan")
    fake = _FakeSupabase([report])

    _run(monkeypatch, fake, report)

    assert fake.incidents[0]["incident_type"] == "penyerangan"
    assert fake.reports[0]["extracted_incident_type"] == "penyerangan"


def test_without_gemini_and_without_hint_the_incident_type_stays_empty(monkeypatch, stubs):
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: None)
    report = _report()
    fake = _FakeSupabase([report])

    _run(monkeypatch, fake, report)

    assert fake.incidents[0]["incident_type"] is None


def test_the_hint_is_not_sent_to_gemini_or_the_embedding(monkeypatch, stubs):
    seen = {}
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda text: seen.setdefault("extract", text))
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda text: seen.setdefault("embed", text) and [0.1] * 768)
    report = _report(incident_type_hint="klitih")
    fake = _FakeSupabase([report])

    _run(monkeypatch, fake, report)

    assert seen["extract"] == report["description"] and seen["embed"] == report["description"]
