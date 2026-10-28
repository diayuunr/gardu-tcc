import logging
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.agents import verify_agent
from app.core.db_retry import execute_with_retry
from app.core.supabase_client import get_supabase


class _FakeResponse:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    """Emulasi minimal query builder Supabase yang dipakai verify_agent.py:
    select/insert/update + eq/neq/limit, semuanya chainable lalu .execute().
    """

    def __init__(self, table: "_FakeTable", op: str, payload=None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, str, object]] = []
        self._count_mode = False

    def select(self, _cols, count=None):
        self._count_mode = count == "exact"
        return self

    def eq(self, key, value):
        self._filters.append(("eq", key, value))
        return self

    def neq(self, key, value):
        self._filters.append(("neq", key, value))
        return self

    def limit(self, _n):
        return self

    def _matches(self, row) -> bool:
        for kind, key, value in self._filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "neq" and row.get(key) == value:
                return False
        return True

    def execute(self):
        rows = self._table.rows
        if self._op == "select":
            matched = [r for r in rows if self._matches(r)]
            if self._count_mode:
                return _FakeResponse(matched, count=len(matched))
            return _FakeResponse(matched)

        if self._op == "insert":
            new_row = dict(self._payload)
            new_row.setdefault("id", str(uuid.uuid4()))
            rows.append(new_row)
            return _FakeResponse([new_row])

        if self._op == "update":
            updated = []
            for row in rows:
                if self._matches(row):
                    row.update(self._payload)
                    updated.append(row)
            return _FakeResponse(updated)

        raise AssertionError(f"Operasi tidak dikenal: {self._op}")


class _FakeTable:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def select(self, cols, count=None):
        return _FakeQuery(self, "select").select(cols, count=count)

    def insert(self, payload):
        return _FakeQuery(self, "insert", payload)

    def update(self, payload):
        return _FakeQuery(self, "update", payload)


class _FakeRpcCall:
    def __init__(self, matches):
        self._matches = matches

    def execute(self):
        return _FakeResponse(self._matches)


class _FakeSupabase:
    """Pengganti Supabase Client — state `reports`/`incidents` in-memory,
    plus `rpc()` yang hasilnya diatur manual per test (mengganti pencarian
    kemiripan pgvector asli).
    """

    def __init__(self, reports: list[dict], incidents: list[dict] | None = None, rpc_matches=None):
        self._tables = {"reports": _FakeTable(reports), "incidents": _FakeTable(incidents or [])}
        self._rpc_matches = rpc_matches or []
        self.rpc_calls: list[dict] = []

    def table(self, name):
        return self._tables[name]

    def rpc(self, _name, params):
        self.rpc_calls.append(params)
        return _FakeRpcCall(self._rpc_matches)


def _make_report(**overrides) -> dict:
    report = {
        "id": str(uuid.uuid4()),
        "description": "Ada sekelompok remaja membawa senjata tajam di simpang jalan.",
        "location_text": "Simpang Jl. Kaliurang km 5",
        "latitude": -7.75,
        "longitude": 110.37,
        "occurred_at": datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc).isoformat(),
        "incident_id": None,
        "status": "menunggu_verifikasi",
    }
    report.update(overrides)
    return report


@pytest.fixture(autouse=True)
def _patch_ai_calls(monkeypatch):
    """Default: ekstraksi & embedding sukses dengan nilai tetap, supaya tiap
    test fokus ke logic clustering-nya, bukan ke panggilan AI asli.
    """
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda _desc: "penyerangan")
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda _desc: [0.1] * 768)
    yield


@pytest.fixture(autouse=True)
def risk_refresh_calls(monkeypatch):
    """Pemicu Risk Prediction Agent di-MOCK (tanpa perhitungan/DB asli) dan
    dicatat, supaya test bisa memverifikasi kapan pemicu itu dipanggil."""
    calls: list[str] = []
    monkeypatch.setattr(verify_agent, "refresh_risk_scores_safely", lambda: calls.append("refresh"))
    return calls


def test_creates_solo_incident_when_no_similar_report(monkeypatch, risk_refresh_calls):
    report = _make_report()
    fake_supabase = _FakeSupabase(reports=[report], rpc_matches=[])
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake_supabase)

    verify_agent.process_report_verification(report["id"])

    assert report["extracted_incident_type"] == "penyerangan"
    assert report["embedding"] == [0.1] * 768
    assert report["incident_id"] is not None
    # Belum ada korroborasi -> status TIDAK berubah dari menunggu_verifikasi (REQ-F-013).
    assert report["status"] == "menunggu_verifikasi"
    assert len(fake_supabase._tables["incidents"].rows) == 1
    # REQ-F-022: insiden belum terverifikasi TIDAK boleh memicu pembaruan skor risiko.
    assert risk_refresh_calls == []


def test_joins_existing_report_into_new_cluster_and_promotes(monkeypatch, risk_refresh_calls):
    new_report = _make_report()
    existing_report = _make_report(incident_id=None, status="menunggu_verifikasi")
    fake_supabase = _FakeSupabase(
        reports=[new_report, existing_report],
        rpc_matches=[
            {"id": existing_report["id"], "incident_id": None, "similarity": 0.88}
        ],
    )
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake_supabase)

    verify_agent.process_report_verification(new_report["id"])

    # REQ-F-022 + SRS fig4 langkah 5: insiden terverifikasi -> Risk Prediction Agent dipicu.
    assert risk_refresh_calls == ["refresh"]
    # REQ-F-011: kedua laporan tergabung ke insiden yang sama.
    assert new_report["incident_id"] is not None
    assert existing_report["incident_id"] == new_report["incident_id"]
    # REQ-F-013: >=2 laporan independen -> status naik jadi terverifikasi.
    assert new_report["status"] == "terverifikasi"
    assert existing_report["status"] == "terverifikasi"
    incident = fake_supabase._tables["incidents"].rows[0]
    assert incident["status"] == "terverifikasi"


def test_flags_near_identical_report_as_duplicate_not_independent_evidence(monkeypatch):
    new_report = _make_report()
    fake_supabase = _FakeSupabase(
        reports=[new_report],
        rpc_matches=[
            {"id": str(uuid.uuid4()), "incident_id": "insiden-lama", "similarity": 0.99}
        ],
    )
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake_supabase)

    verify_agent.process_report_verification(new_report["id"])

    # REQ-F-012: kemiripan sangat tinggi -> ditandai duplikat, bukan ikut klaster begitu saja.
    assert new_report["status"] == "ditandai_duplikat"
    assert new_report["incident_id"] is None


def test_duplicate_flagged_report_never_counts_toward_verification(monkeypatch):
    """REQ-F-013: laporan berstatus ditandai_duplikat TIDAK ikut dihitung
    sebagai laporan independen, bahkan kalau (hipotetis) sudah terlanjur
    ter-link ke incident_id yang sama — jadi klaster dengan 1 laporan asli
    + 1 laporan duplikat TIDAK dipromosikan jadi terverifikasi.
    """
    incident_id = "insiden-1"
    independent_report = _make_report(incident_id=incident_id, status="menunggu_verifikasi")
    duplicate_report = _make_report(incident_id=incident_id, status="ditandai_duplikat")
    fake_supabase = _FakeSupabase(reports=[independent_report, duplicate_report])

    verify_agent._promote_incident_if_verified(fake_supabase, incident_id)

    # Cuma 1 laporan independen (yang duplikat tidak ikut dihitung) -> belum promosi.
    assert independent_report["status"] == "menunggu_verifikasi"
    assert fake_supabase._tables["incidents"].rows == []


def test_survives_total_ai_failure_without_raising(monkeypatch):
    """REQ-NF-110: laporan mentah tidak boleh rusak walau AI Agent gagal total."""
    report = _make_report()
    fake_supabase = _FakeSupabase(reports=[report])
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(
        verify_agent,
        "extract_incident_type",
        lambda _desc: (_ for _ in ()).throw(RuntimeError("AI down")),
    )

    # Tidak boleh melempar exception ke pemanggil (background task).
    verify_agent.process_report_verification(report["id"])

    assert report["status"] == "menunggu_verifikasi"
    assert report.get("embedding") is None
    assert report["incident_id"] is None


def test_execute_retries_once_when_supabase_connection_drops():
    """Regresi dari tes beban 20 laporan paralel: koneksi HTTP/2 bersama kadang
    diputus server (RemoteProtocolError). Retry sekali sudah cukup."""

    class _FlakyQuery:
        def __init__(self):
            self.calls = 0

        def execute(self):
            self.calls += 1
            if self.calls == 1:
                raise httpx.RemoteProtocolError("Server disconnected")
            return _FakeResponse([{"ok": True}])

    query = _FlakyQuery()

    response = execute_with_retry(query)

    assert response.data == [{"ok": True}]
    assert query.calls == 2


def test_agent_does_not_raise_when_connection_drops_twice(monkeypatch):
    """Putus 2x berturut-turut: retry berhenti di 1x, exception ditelan
    try/except terluar (REQ-NF-110) — tidak boleh bocor ke background task."""

    class _AlwaysDisconnectedSupabase:
        execute_calls = 0

        def table(self, _name):
            return self

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            type(self).execute_calls += 1
            raise httpx.RemoteProtocolError("Server disconnected")

    monkeypatch.setattr(verify_agent, "get_supabase", lambda: _AlwaysDisconnectedSupabase())

    verify_agent.process_report_verification(str(uuid.uuid4()))  # tidak boleh raise

    assert _AlwaysDisconnectedSupabase.execute_calls == 2  # percobaan awal + tepat 1 retry


def test_outer_handler_log_never_contains_report_text_or_traceback(monkeypatch, caplog):
    """Handler terluar dulu memakai logger.exception (traceback + pesan error
    penuh, bisa memuat teks laporan). Sekarang hanya tipe error + lokasi kode."""
    report = _make_report()
    fake_supabase = _FakeSupabase(reports=[report])
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: fake_supabase)

    def leaky_failure(_description):
        raise RuntimeError("gagal memproses RAHASIA-LAPORAN nomor hp 081234567890")

    monkeypatch.setattr(verify_agent, "extract_incident_type", leaky_failure)

    with caplog.at_level(logging.DEBUG, logger="app.agents.verify_agent"):
        verify_agent.process_report_verification(report["id"])

    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert any(
        record.levelno == logging.ERROR
        and "RuntimeError" in record.getMessage()
        and "gagal total" in record.getMessage()
        for record in caplog.records
    )


def test_get_supabase_still_importable_reference():
    """Sanity check kecil: pastikan verify_agent memang pakai get_supabase
    dari app.core.supabase_client (bukan client ad-hoc terpisah)."""
    assert verify_agent.get_supabase is get_supabase
