"""Keputusan moderator (REQ-F-060/061) dan sinkronisasi insiden sesudahnya.

Tiga keputusan terhadap sebuah laporan:

- `terverifikasi` (setujui)  : status + `moderation_decision='disetujui'`. Insiden laporan (dibuat bila belum
                               ada) menjadi terverifikasi walau hanya satu laporan — manusia sudah menilainya.
- `ditandai_hoaks` (tolak)   : status + `moderation_decision='ditolak'`, `flagged_reason='ditolak_moderator'`.
                               Laporan DICABUT dari insidennya (invarian: laporan ditandai tidak pernah punya
                               `incident_id`, sama seperti penandaan otomatis).
- `menunggu_verifikasi`      : keputusan dihapus, laporan dicabut dari insiden dan menunggu diklasterkan ulang
                               (job reprocess mengambilnya karena `incident_id` kosong).

Sesudahnya `sync_incident` menghitung ulang insiden yang terdampak dengan aturan yang sama dengan promosi otomatis
(`verify_agent`): terverifikasi bila >= 2 laporan independen ATAU ada anggota yang disetujui moderator; tanpa itu
turun ke `baru` dan anggota yang tadinya terverifikasi otomatis kembali `menunggu_verifikasi`; tanpa anggota,
insiden komunitas dihapus. Insiden seed data TIDAK PERNAH diubah. Skor kerawanan dihitung ulang (di latar belakang
oleh pemanggil) bila status terverifikasi sebuah insiden berubah.

Rangkaian pembaruan ini tidak satu transaksi (Supabase REST); setiap langkah idempoten, jadi mengulang keputusan
yang sama memulihkan keadaan yang terpotong di tengah jalan.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from supabase import Client

from app.agents.verify_agent import (
    FLAGGED_STATUSES,
    STATUS_DUPLICATE,
    STATUS_HOAX,
    STATUS_PENDING,
    _create_incident,
)
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

STATUS_VERIFIED = "terverifikasi"
INCIDENT_NEW = "baru"
INCIDENT_DELETED = "dihapus"
DECISION_APPROVED = "disetujui"
DECISION_REJECTED = "ditolak"
REASON_REJECTED_BY_MODERATOR = "ditolak_moderator"

TARGET_STATUSES = frozenset({STATUS_VERIFIED, STATUS_HOAX, STATUS_PENDING})
REPORT_COLUMNS = (
    "id,public_number,status,flagged_reason,moderation_decision,description,location_text,occurred_at,created_at,"
    "extracted_incident_type,incident_type_hint,incident_id"
)


class ReportNotFound(Exception):
    """Laporan dengan id itu tidak ada."""


@dataclass
class ModerationOutcome:
    report_status: str
    changed: bool
    incident_status: str | None = None  # status insiden laporan sesudah keputusan; None = tidak terhubung
    refresh_scores: bool = False
    touched_incidents: list[str] = field(default_factory=list)


def public_number_label(number: object) -> str:
    """Id pendek publik, mis. 123 -> "GRD-000123"."""
    try:
        return f"GRD-{int(number):06d}"
    except (TypeError, ValueError):
        return "GRD-??????"


# ------------------------------------------------------------------ daftar


def list_reports(supabase: Client, statuses: list[str], limit: int, offset: int) -> tuple[list[dict], int]:
    """Laporan berstatus tertentu, terbaru dulu. Return (baris, total)."""
    response = execute_with_retry(
        supabase.table("reports")
        .select(REPORT_COLUMNS, count="exact")
        .in_("status", statuses)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
    )
    return response.data or [], response.count or 0


# ----------------------------------------------------------- sinkronisasi insiden


def sync_incident(supabase: Client, incident_id: str) -> tuple[str, bool]:
    """Hitung ulang satu insiden dari anggotanya. Return (status akhir: baru|terverifikasi|dihapus, apakah status
    terverifikasi-nya BERUBAH sehingga skor perlu dihitung ulang)."""
    rows = execute_with_retry(
        supabase.table("incidents").select("id,status,is_seed_data").eq("id", incident_id).limit(1)
    ).data
    if not rows:
        return INCIDENT_DELETED, False
    incident = rows[0]
    if incident.get("is_seed_data"):
        return str(incident["status"]), False  # data seed bukan hasil laporan warga: tidak disentuh

    was_verified = incident["status"] == STATUS_VERIFIED
    members = execute_with_retry(
        supabase.table("reports")
        .select("id,status,moderation_decision")
        .eq("incident_id", incident_id)
        .neq("status", STATUS_DUPLICATE)
        .neq("status", STATUS_HOAX)
    ).data or []

    if not members:
        execute_with_retry(supabase.table("incidents").delete().eq("id", incident_id))
        logger.info("Insiden %s dihapus: tidak ada laporan independen tersisa", incident_id)
        return INCIDENT_DELETED, was_verified

    verified = len(members) >= 2 or any(m.get("moderation_decision") == DECISION_APPROVED for m in members)
    if verified:
        new_status = STATUS_VERIFIED
        stale = [m["id"] for m in members if m["status"] != STATUS_VERIFIED]
        target_member_status = STATUS_VERIFIED
    else:
        # Satu laporan tanpa persetujuan moderator: status "terverifikasi" tadinya hasil promosi otomatis.
        new_status = INCIDENT_NEW
        stale = [m["id"] for m in members if m["status"] == STATUS_VERIFIED]
        target_member_status = STATUS_PENDING
    if stale:  # hanya tulis bila ada yang berbeda (mengulang keputusan yang sama tidak menulis apa pun)
        execute_with_retry(supabase.table("reports").update({"status": target_member_status}).in_("id", stale))
    if incident["status"] != new_status:
        execute_with_retry(supabase.table("incidents").update({"status": new_status}).eq("id", incident_id))
    return new_status, was_verified != verified


# ----------------------------------------------------------------- keputusan


def _fetch_report(supabase: Client, report_id: str) -> dict | None:
    rows = execute_with_retry(
        supabase.table("reports")
        .select(
            "id,status,incident_id,moderation_decision,location_text,latitude,longitude,occurred_at,"
            "extracted_incident_type,incident_type_hint"
        )
        .eq("id", report_id)
        .limit(1)
    ).data
    return rows[0] if rows else None


def _already_decided(report: dict, target: str) -> bool:
    if report["status"] != target:
        return False
    expected = {STATUS_VERIFIED: DECISION_APPROVED, STATUS_HOAX: DECISION_REJECTED}.get(target)
    return report.get("moderation_decision") == expected


def apply_decision(supabase: Client, report_id: str, target: str, moderator_id: str) -> ModerationOutcome:
    """Terapkan keputusan moderator lalu sinkronkan insiden yang terdampak. Melempar `ReportNotFound`."""
    if target not in TARGET_STATUSES:
        raise ValueError("status tujuan tidak diizinkan")
    report = _fetch_report(supabase, report_id)
    if report is None:
        raise ReportNotFound(report_id)

    old_incident = report.get("incident_id")
    if _already_decided(report, target):
        incident_status = sync_incident(supabase, old_incident)[0] if old_incident else None
        return ModerationOutcome(target, changed=False, incident_status=_public_incident_status(incident_status))

    audit = {"moderated_at": datetime.now(timezone.utc).isoformat(), "moderated_by": moderator_id}
    outcome = ModerationOutcome(report_status=target, changed=True)

    if target == STATUS_VERIFIED:
        execute_with_retry(
            supabase.table("reports").update({"status": STATUS_VERIFIED, "moderation_decision": DECISION_APPROVED, **audit}).eq("id", report_id)
        )
        _clear_flag_reason(supabase, report_id)
        incident_id = old_incident or _create_incident(
            supabase, report, report.get("extracted_incident_type") or report.get("incident_type_hint")
        )
        if not old_incident:
            execute_with_retry(supabase.table("reports").update({"incident_id": incident_id}).eq("id", report_id))
            # Insiden baru lahir 'baru'; sync_incident menaikkannya (anggota disetujui moderator).
            outcome.refresh_scores = True
        status, changed = sync_incident(supabase, incident_id)
        outcome.incident_status = _public_incident_status(status)
        outcome.refresh_scores = outcome.refresh_scores or changed
        outcome.touched_incidents.append(incident_id)
        return outcome

    if target == STATUS_HOAX:
        update = {"status": STATUS_HOAX, "moderation_decision": DECISION_REJECTED, "incident_id": None, **audit}
    else:  # kembali menunggu
        update = {"status": STATUS_PENDING, "moderation_decision": None, "incident_id": None, **audit}
    execute_with_retry(supabase.table("reports").update(update).eq("id", report_id))
    if target == STATUS_HOAX:
        _set_flag_reason(supabase, report_id, REASON_REJECTED_BY_MODERATOR)
    else:
        _clear_flag_reason(supabase, report_id)

    if old_incident:
        _status, changed = sync_incident(supabase, old_incident)
        outcome.refresh_scores = changed
        outcome.touched_incidents.append(old_incident)
    return outcome


def _public_incident_status(status: str | None) -> str | None:
    return status if status in (INCIDENT_NEW, STATUS_VERIFIED) else None


def _set_flag_reason(supabase: Client, report_id: str, reason: str | None) -> None:
    """Alasan penandaan hanya pelengkap: gagal menulisnya (kolom belum dimigrasi) tidak membatalkan keputusan."""
    try:
        execute_with_retry(supabase.table("reports").update({"flagged_reason": reason}).eq("id", report_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("flagged_reason tidak tersimpan: %s", safe_error_summary(exc))


def _clear_flag_reason(supabase: Client, report_id: str) -> None:
    _set_flag_reason(supabase, report_id, None)


__all__ = [
    "FLAGGED_STATUSES",
    "ModerationOutcome",
    "ReportNotFound",
    "TARGET_STATUSES",
    "apply_decision",
    "list_reports",
    "public_number_label",
    "sync_incident",
]
