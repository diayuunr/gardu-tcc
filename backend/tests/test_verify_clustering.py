"""Tes Tahap 1 Verification Agent: V1 zona waktu, V2 kecocokan ditandai, V3 koordinat insiden,
V4 heuristik hoaks, V5 reprocessing idempoten, V6 penggabungan banyak insiden.

Fake Supabase di sini berperilaku nyata (filter eq/neq/in_/lt/or_, insert/update/delete atas
daftar baris in-memory) — bukan mock yang selalu lulus.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.reports as reports_module
from app.agents import verify_agent
from app.agents.risk_agent import WIB, time_bucket_of
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app
from app.schemas.report import ReportCreate
from app.scripts import reprocess_reports as reprocess

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
CLEAN_TEXT = "Ada sekelompok remaja membawa senjata tajam di simpang jalan Kaliurang."


# ------------------------------------------------------------- fake Supabase


class _Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table, op, payload=None):
        self._table, self._op, self._payload = table, op, payload
        self._filters: list[tuple] = []
        self._count_mode = False
        self._limit = None

    def select(self, _cols, count=None):
        self._count_mode = count == "exact"
        return self

    def eq(self, key, value):
        self._filters.append(("eq", key, value))
        return self

    def neq(self, key, value):
        self._filters.append(("neq", key, value))
        return self

    def in_(self, key, values):
        self._filters.append(("in", key, list(values)))
        return self

    def lt(self, key, value):
        self._filters.append(("lt", key, value))
        return self

    def or_(self, expression):
        # "kolom.is.null,kolom2.is.null" -> salah satu kolom bernilai None
        columns = [part.split(".is.null")[0] for part in expression.split(",")]
        self._filters.append(("any_null", columns, None))
        return self

    def order(self, _column):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matches(self, row) -> bool:
        for kind, key, value in self._filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "neq" and row.get(key) == value:
                return False
            if kind == "in" and row.get(key) not in value:
                return False
            if kind == "lt" and not (row.get(key) is not None and row[key] < value):
                return False
            if kind == "any_null" and not any(row.get(column) is None for column in key):
                return False
        return True

    def execute(self):
        rows = self._table.rows
        if self._op == "select":
            matched = [row for row in rows if self._matches(row)]
            if self._limit is not None:
                matched = matched[: self._limit]
            return _Resp(matched, count=len(matched) if self._count_mode else None)
        if self._op == "insert":
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            new_row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
            rows.append(new_row)
            return _Resp([new_row])
        if self._op == "update":
            updated = [row for row in rows if self._matches(row)]
            for row in updated:
                row.update(self._payload)
            return _Resp(updated)
        if self._op == "delete":
            doomed = [row for row in rows if self._matches(row)]
            rows[:] = [row for row in rows if row not in doomed]
            return _Resp(doomed)
        raise AssertionError(self._op)


class _Table:
    def __init__(self, rows):
        self.rows = rows

    def select(self, cols, count=None):
        return _Query(self, "select").select(cols, count=count)

    def insert(self, payload):
        return _Query(self, "insert", payload)

    def update(self, payload):
        return _Query(self, "update", payload)

    def delete(self):
        return _Query(self, "delete")


class _FakeSupabase:
    def __init__(self, reports, incidents=None, rpc_matches=None):
        self.reports = reports
        self.incidents = incidents if incidents is not None else []
        self._tables = {"reports": _Table(self.reports), "incidents": _Table(self.incidents)}
        self._rpc_matches = rpc_matches or []

    def table(self, name):
        return self._tables[name]

    def rpc(self, _name, _params):
        matches = self._rpc_matches
        return SimpleNamespace(execute=lambda: _Resp(matches))


def _report(**overrides) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "description": CLEAN_TEXT,
        "location_text": "Simpang Jl. Kaliurang km 5",
        "latitude": -7.75,
        "longitude": 110.37,
        "occurred_at": datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc).isoformat(),
        "incident_id": None,
        "status": "menunggu_verifikasi",
        "extracted_incident_type": None,
        "embedding": None,
        "created_at": "2026-09-19T21:30:00+00:00",
    }
    row.update(overrides)
    return row


def _incident(**overrides) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "location_text": "Kaliurang",
        "latitude": -7.75,
        "longitude": 110.37,
        "status": "baru",
        "is_seed_data": False,
        "created_at": "2026-09-19T10:00:00+00:00",
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _ai_and_risk_stubs(monkeypatch):
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: "penyerangan")
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _d: [0.1] * 768)
    calls: list[str] = []
    monkeypatch.setattr(verify_agent, "refresh_risk_scores_safely", lambda: calls.append("refresh"))
    return calls


def _run(monkeypatch, fake, report):
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake)
    verify_agent.process_report_verification(report["id"])


# ============================================================ V1: zona waktu


def test_naive_occurred_at_is_wib_not_utc_and_keeps_its_hour_bucket():
    report = ReportCreate(
        description=CLEAN_TEXT, location_text="Kaliurang", occurred_at=datetime(2026, 9, 20, 2, 0)
    )

    assert report.occurred_at.utcoffset() == timedelta(hours=7)  # tidak bergeser ke UTC
    assert report.occurred_at.hour == 2
    assert time_bucket_of(report.occurred_at) == "dini_hari"
    assert report.occurred_at.isoformat().endswith("+07:00")


def test_future_check_uses_the_normalized_value_so_a_naive_wib_now_is_not_rejected():
    now_wib_naive = datetime.now(WIB).replace(tzinfo=None) - timedelta(minutes=1)

    accepted = ReportCreate(description=CLEAN_TEXT, location_text="Kaliurang", occurred_at=now_wib_naive)
    assert accepted.occurred_at.tzinfo is not None  # kode lama menganggapnya UTC -> "masa depan" 7 jam

    for future in (now_wib_naive + timedelta(hours=2), datetime.now(timezone.utc) + timedelta(hours=2)):
        with pytest.raises(ValidationError, match="masa depan"):
            ReportCreate(description=CLEAN_TEXT, location_text="Kaliurang", occurred_at=future)


def test_api_stores_naive_time_as_timezone_aware_wib(monkeypatch):
    saved: list[dict] = []

    class _Table:
        def insert(self, record):
            saved.append(record)
            return self

        def execute(self):
            return SimpleNamespace(
                data=[{"id": "r-1", "status": "menunggu_verifikasi", "created_at": "2026-09-20T00:00:00+00:00"}]
            )

    monkeypatch.setattr(reports_module, "process_report_verification", lambda _id: None)
    app.dependency_overrides[get_supabase] = lambda: SimpleNamespace(table=lambda _n: _Table())
    naive = (datetime.now(WIB) - timedelta(hours=3)).replace(tzinfo=None, microsecond=0)
    try:
        response = TestClient(app).post(
            "/reports",
            json={"description": CLEAN_TEXT, "location_text": "Kaliurang", "occurred_at": naive.isoformat()},
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 201
    assert saved[0]["occurred_at"] == naive.replace(tzinfo=WIB).isoformat()


# ====================================================== V2: kecocokan ditandai


@pytest.mark.parametrize("flagged_status", ["ditandai_duplikat", "ditandai_hoaks"])
def test_flagged_matches_are_ignored_and_never_get_an_incident(monkeypatch, flagged_status):
    new = _report()
    flagged = _report(status=flagged_status, incident_id="insiden-lama")
    fake = _FakeSupabase(
        [new, flagged],
        rpc_matches=[{"id": flagged["id"], "incident_id": "insiden-lama", "similarity": 0.99}],
    )

    _run(monkeypatch, fake, new)

    # Kode lama: similarity 0.99 -> new ditandai duplikat dari laporan yang SUDAH duplikat/hoaks.
    assert new["status"] == "menunggu_verifikasi"
    assert len(fake.incidents) == 1 and new["incident_id"] == fake.incidents[0]["id"]  # insiden baru, bukan "insiden-lama"
    assert flagged["incident_id"] == "insiden-lama"  # laporan ditandai tidak disentuh


def test_flagged_match_is_not_pulled_into_a_new_cluster_when_a_valid_match_exists(monkeypatch):
    new = _report()
    valid = _report()
    flagged = _report(status="ditandai_hoaks")
    fake = _FakeSupabase(
        [new, valid, flagged],
        rpc_matches=[
            {"id": flagged["id"], "incident_id": None, "similarity": 0.9},
            {"id": valid["id"], "incident_id": None, "similarity": 0.88},
        ],
    )

    _run(monkeypatch, fake, new)

    assert new["incident_id"] == valid["incident_id"] is not None
    assert flagged["incident_id"] is None  # tidak boleh diberi incident_id (kode lama memberinya)


def test_sql_function_migration_filters_flagged_statuses():
    sql = (MIGRATIONS / "20260921000000_match_similar_reports_exclude_flagged.sql").read_text(encoding="utf-8")
    down = (MIGRATIONS / "20260921000000_match_similar_reports_exclude_flagged_down.sql").read_text(encoding="utf-8")

    assert "r.status not in ('ditandai_duplikat', 'ditandai_hoaks')" in sql
    assert "status" not in down.split("as $$", 1)[1].split("$$;", 1)[0]  # _down mengembalikan versi lama


# =================================================== V3: koordinat insiden


def test_incident_created_without_creator_coordinates_borrows_them_from_a_matched_report(monkeypatch):
    new = _report(latitude=None, longitude=None)
    neighbour = _report(latitude=-7.77, longitude=110.38)
    fake = _FakeSupabase(
        [new, neighbour], rpc_matches=[{"id": neighbour["id"], "incident_id": None, "similarity": 0.88}]
    )

    _run(monkeypatch, fake, new)

    incident = fake.incidents[0]
    assert (incident["latitude"], incident["longitude"]) == (-7.77, 110.38)  # kode lama: NULL


def test_creator_coordinates_win_over_matched_report_coordinates(monkeypatch):
    new = _report(latitude=-7.75, longitude=110.37)
    neighbour = _report(latitude=-7.99, longitude=110.99)
    fake = _FakeSupabase(
        [new, neighbour], rpc_matches=[{"id": neighbour["id"], "incident_id": None, "similarity": 0.88}]
    )

    _run(monkeypatch, fake, new)

    assert (fake.incidents[0]["latitude"], fake.incidents[0]["longitude"]) == (-7.75, 110.37)


def test_coordinates_are_filled_in_when_a_located_report_joins_a_coordinate_less_incident(monkeypatch):
    incident = _incident(latitude=None, longitude=None)
    member = _report(incident_id=incident["id"], latitude=None, longitude=None)
    new = _report(latitude=-7.76, longitude=110.39)
    fake = _FakeSupabase(
        [new, member],
        incidents=[incident],
        rpc_matches=[{"id": member["id"], "incident_id": incident["id"], "similarity": 0.88}],
    )

    _run(monkeypatch, fake, new)

    assert (incident["latitude"], incident["longitude"]) == (-7.76, 110.39)


def test_existing_incident_coordinates_are_never_overwritten(monkeypatch):
    incident = _incident(latitude=-7.70, longitude=110.30)
    member = _report(incident_id=incident["id"])
    new = _report(latitude=-7.99, longitude=110.99)
    fake = _FakeSupabase(
        [new, member],
        incidents=[incident],
        rpc_matches=[{"id": member["id"], "incident_id": incident["id"], "similarity": 0.88}],
    )

    _run(monkeypatch, fake, new)

    assert (incident["latitude"], incident["longitude"]) == (-7.70, 110.30)


# ================================================== V4: heuristik hoaks


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("1234567890 !!!", verify_agent.REASON_NO_LETTERS),
        ("!!!!!!!!!!!!", verify_agent.REASON_NO_LETTERS),
        ("aaaaaaaaaaaaaaa", verify_agent.REASON_REPEATED_CHARS),
        ("hahahahahahaha", verify_agent.REASON_REPEATED_CHARS),
        ("asdasdasdasdasd", verify_agent.REASON_REPEATED_CHARS),
        ("tolong tolong tolong tolong tolong", verify_agent.REASON_REPEATED_WORD),
    ],
)
def test_clearly_junk_text_is_given_a_reason(text, reason):
    assert verify_agent.assess_report_text(text, get_settings()) == reason


@pytest.mark.parametrize(
    "text",
    [
        CLEAN_TEXT,
        "Motor dihadang dua orang di Jl. Parangtritis km 7, korban jatuh.",
        "Ada orang bawa pedang di depan ruko, jam 2 pagi.",
        "klitih lagi di ring road, hati-hati",  # singkat tapi sah
        "Kejadian pukul 23.30 di jalan Godean, 3 motor, 5 orang",
        "tolong tolong ada begal di sini",  # kata berulang tapi ada kata lain
    ],
)
def test_legitimate_reports_are_never_flagged(text):
    assert verify_agent.assess_report_text(text, get_settings()) is None


def test_junk_report_is_flagged_hoax_before_any_ai_call_and_gets_no_incident(monkeypatch):
    junk = _report(description="aaaaaaaaaaaaaaaa")
    fake = _FakeSupabase([junk])

    def must_not_call(_description):
        raise AssertionError("AI tidak boleh dipanggil untuk teks sampah")

    monkeypatch.setattr(verify_agent, "extract_incident_type", must_not_call)
    monkeypatch.setattr(verify_agent, "generate_embedding", must_not_call)

    _run(monkeypatch, fake, junk)

    assert junk["status"] == "ditandai_hoaks"
    assert junk["flagged_reason"] == verify_agent.REASON_REPEATED_CHARS
    assert junk["incident_id"] is None and fake.incidents == []


def test_hoax_reason_failure_does_not_undo_the_flag(monkeypatch):
    """Kolom flagged_reason belum dimigrasi -> update alasan gagal; status hoaks tetap tersimpan."""
    junk = _report(description="aaaaaaaaaaaaaaaa")
    fake = _FakeSupabase([junk])
    original_update = fake._tables["reports"].update

    def update_without_reason_column(payload):
        if "flagged_reason" in payload:
            raise RuntimeError("column flagged_reason does not exist")
        return original_update(payload)

    fake._tables["reports"].update = update_without_reason_column

    _run(monkeypatch, fake, junk)

    assert junk["status"] == "ditandai_hoaks"


def test_duplicate_flag_records_a_reason_code(monkeypatch):
    new = _report()
    original = _report()
    fake = _FakeSupabase(
        [new, original], rpc_matches=[{"id": original["id"], "incident_id": None, "similarity": 0.99}]
    )

    _run(monkeypatch, fake, new)

    assert (new["status"], new["flagged_reason"]) == ("ditandai_duplikat", verify_agent.REASON_SIMILAR_REPORT)


# ====================================================== V5: reprocessing


def _aged(**overrides):
    return _report(created_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), **overrides)


def _reprocess(fake, monkeypatch, **kwargs):
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake)
    return reprocess.reprocess_reports(
        fake,
        limit=50,
        delay_seconds=0,
        min_age_minutes=10,
        sleep=lambda _s: None,
        **{"dry_run": False, **kwargs},
    )


def test_reprocess_picks_only_unfinished_pending_and_old_enough_reports(monkeypatch):
    orphan_no_embedding = _aged()
    orphan_no_type = _aged(embedding=[0.1], extracted_incident_type=None, incident_id="i-1")
    complete = _aged(embedding=[0.1], extracted_incident_type="x", incident_id="i-2")
    just_submitted = _report(created_at=datetime.now(timezone.utc).isoformat())  # masih diproses background task
    flagged = _aged(status="ditandai_hoaks")
    fake = _FakeSupabase([orphan_no_embedding, orphan_no_type, complete, just_submitted, flagged])

    summary = _reprocess(fake, monkeypatch, dry_run=True)

    assert set(summary.report_ids) == {orphan_no_embedding["id"], orphan_no_type["id"]}


def test_dry_run_changes_nothing_and_calls_no_ai(monkeypatch):
    orphan = _aged()
    fake = _FakeSupabase([orphan])
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _d: pytest.fail("dry run memanggil AI"))

    summary = _reprocess(fake, monkeypatch, dry_run=True)

    assert (summary.found, summary.processed, summary.dry_run) == (1, 0, True)
    assert orphan["embedding"] is None and fake.incidents == []


def test_reprocessing_is_idempotent_and_never_duplicates_incidents(monkeypatch):
    orphan = _aged()
    fake = _FakeSupabase([orphan])

    first = _reprocess(fake, monkeypatch)
    second = _reprocess(fake, monkeypatch)

    assert first.processed == 1
    assert orphan["extracted_incident_type"] == "penyerangan" and orphan["embedding"] is not None
    assert len(fake.incidents) == 1  # satu insiden, tidak ganda
    assert second.found == 0  # laporan sudah lengkap -> tidak diambil lagi


def test_reprocessing_a_report_that_is_already_clustered_only_fills_the_missing_type(monkeypatch):
    incident = _incident()
    clustered = _aged(embedding=[0.1], incident_id=incident["id"])
    fake = _FakeSupabase([clustered], incidents=[incident])
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _d: pytest.fail("tidak perlu embedding ulang"))

    _reprocess(fake, monkeypatch)
    _reprocess(fake, monkeypatch)

    assert clustered["extracted_incident_type"] == "penyerangan"
    assert clustered["incident_id"] == incident["id"] and fake.incidents == [incident]


def test_processing_skips_reports_whose_status_already_changed(monkeypatch):
    done = _aged(status="terverifikasi")
    fake = _FakeSupabase([done])
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _d: pytest.fail("seharusnya dilewati"))

    _run(monkeypatch, fake, done)

    assert fake.incidents == []


def test_reprocess_waits_between_reports_but_not_before_the_first_or_in_dry_run(monkeypatch):
    fake = _FakeSupabase([_aged(), _aged(), _aged()])
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake)
    sleeps: list[float] = []
    processed: list[str] = []

    reprocess.reprocess_reports(
        fake, dry_run=False, limit=10, delay_seconds=4.0, min_age_minutes=10,
        process=processed.append, sleep=sleeps.append,
    )
    assert len(processed) == 3 and sleeps == [4.0, 4.0]

    sleeps.clear()
    reprocess.reprocess_reports(
        fake, dry_run=True, limit=10, delay_seconds=4.0, min_age_minutes=10,
        process=processed.append, sleep=sleeps.append,
    )
    assert sleeps == []


# ============================================ V6: banyak insiden -> tertua


def test_multiple_matched_incidents_are_merged_into_the_oldest(monkeypatch):
    oldest = _incident(created_at="2026-09-19T08:00:00+00:00")
    newer = _incident(created_at="2026-09-19T11:00:00+00:00")
    newest = _incident(created_at="2026-09-19T12:00:00+00:00")
    in_oldest = _report(incident_id=oldest["id"])
    in_newer = _report(incident_id=newer["id"])
    in_newest = _report(incident_id=newest["id"])
    new = _report()
    fake = _FakeSupabase(
        [new, in_newer, in_oldest, in_newest],
        incidents=[newer, oldest, newest],
        rpc_matches=[  # urutan similarity: yang BUKAN tertua datang lebih dulu
            {"id": in_newer["id"], "incident_id": newer["id"], "similarity": 0.9},
            {"id": in_oldest["id"], "incident_id": oldest["id"], "similarity": 0.88},
            {"id": in_newest["id"], "incident_id": newest["id"], "similarity": 0.85},
        ],
    )

    _run(monkeypatch, fake, new)

    assert [i["id"] for i in fake.incidents] == [oldest["id"]]  # yang lebih baru dihapus (tak ada hitungan ganda)
    assert {r["incident_id"] for r in (new, in_newer, in_oldest, in_newest)} == {oldest["id"]}
    assert oldest["status"] == "terverifikasi"  # 4 laporan independen sekarang satu klaster


def test_seed_data_incidents_are_never_merged_or_deleted(monkeypatch):
    seed = _incident(is_seed_data=True, created_at="2020-01-01T00:00:00+00:00")
    community = _incident(created_at="2026-09-19T11:00:00+00:00")
    member = _report(incident_id=community["id"])
    linked_to_seed = _report(incident_id=seed["id"])
    new = _report()
    fake = _FakeSupabase(
        [new, member, linked_to_seed],
        incidents=[seed, community],
        rpc_matches=[
            {"id": linked_to_seed["id"], "incident_id": seed["id"], "similarity": 0.9},
            {"id": member["id"], "incident_id": community["id"], "similarity": 0.88},
        ],
    )

    _run(monkeypatch, fake, new)

    assert seed in fake.incidents  # tidak dihapus
    assert new["incident_id"] == community["id"]  # digabung ke insiden komunitas, bukan seed
