"""Test Verification & Clustering Agent.

Test A & B butuh GEMINI_API_KEY asli (integration test, panggil Gemini API
sungguhan) -> di-skip otomatis kalau key belum di-set, BUKAN dipalsukan
dengan mock yang seolah-olah hasil AI asli. Test C murni test error-handling
dan tidak butuh key sama sekali (lihat backend/agents/verification.py:
client dibuat lazy, bukan saat modul di-import).
"""

import os
from datetime import datetime, timezone

import pytest

from backend.agents import verification as verification_module
from backend.agents.verification import VerificationError, verify_report
from backend.db.queries import insert_report

HAS_GEMINI_KEY = bool(os.environ.get("GEMINI_API_KEY"))
SKIP_REASON = "GEMINI_API_KEY belum di-set — lihat laporan blocker dari task ini"


@pytest.mark.skipif(not HAS_GEMINI_KEY, reason=SKIP_REASON)
def test_verify_report_extracts_sensible_entities():
    text = "Ada kejadian mencurigakan di Jalan Kaliurang jam 2 pagi"
    report = insert_report(
        {
            "description": text,
            "location": "Jalan Kaliurang",
            "reported_at": datetime.now(timezone.utc).isoformat(),
            "status": "menunggu_verifikasi",
        }
    )

    result = verify_report(report["id"], text)

    assert "kaliurang" in result["location"].lower()
    assert result["time"] == "dini_hari"


@pytest.mark.skipif(not HAS_GEMINI_KEY, reason=SKIP_REASON)
def test_verify_report_finds_cluster_when_similar_reports_exist():
    now_iso = datetime.now(timezone.utc).isoformat()
    location = "Jalan Test Cluster, Sleman"

    for _ in range(2):
        insert_report(
            {
                "description": "Penyerangan di Jalan Test Cluster, Sleman",
                "location": location,
                "reported_at": now_iso,
                "status": "menunggu_verifikasi",
            }
        )

    text = "Ada penyerangan lagi di Jalan Test Cluster, Sleman, dini hari tadi jam 3"
    new_report = insert_report(
        {
            "description": text,
            "location": location,
            "reported_at": now_iso,
            "status": "menunggu_verifikasi",
        }
    )

    result = verify_report(new_report["id"], text)

    assert result["cluster_id"] is not None


def test_verify_report_raises_clear_error_when_ai_call_fails(monkeypatch):
    def _boom(_text):
        raise Exception("simulated network timeout")

    monkeypatch.setattr(verification_module, "_call_gemini", _boom)

    with pytest.raises(VerificationError):
        verify_report("00000000-0000-0000-0000-000000000000", "teks apapun")
