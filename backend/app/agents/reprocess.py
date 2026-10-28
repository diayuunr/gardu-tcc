"""Inti pemrosesan ulang laporan yatim — dipakai skrip CLI (`app.scripts.reprocess_reports`) DAN endpoint internal
(`POST /internal/reprocess`). Modul ini tidak mengatur logging global (berbeda dengan skrip CLI), jadi aman diimpor
oleh server.

"Belum tuntas" = laporan `menunggu_verifikasi` yang tanpa embedding, ATAU tanpa jenis kejadian, ATAU belum
diklasterkan (tanpa incident_id), dan sudah lebih tua dari `reprocess_min_age_minutes` (agar tidak berbenturan dengan
background task POST /reports yang masih berjalan). `process_report_verification` idempoten, jadi memprosesnya dua
kali tidak membuat insiden ganda."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from supabase import Client

from app.agents.verify_agent import STATUS_PENDING, process_report_verification
from app.core.db_retry import execute_with_retry


@dataclass(frozen=True)
class ReprocessSummary:
    report_ids: tuple[str, ...]  # laporan yang ditemukan (dan diproses, kecuali dry run)
    processed: int
    dry_run: bool

    @property
    def found(self) -> int:
        return len(self.report_ids)


def find_unfinished_reports(supabase: Client, limit: int, older_than: datetime) -> list[str]:
    """Id laporan `menunggu_verifikasi` yang belum lengkap, tertua dulu.

    "Belum lengkap" = tanpa embedding, ATAU tanpa jenis kejadian, ATAU belum diklasterkan
    (tanpa incident_id). Yang terakhir ikut diambil karena laporan yang embedding-nya
    tersimpan tetapi klasterisasinya gagal tidak akan pernah terjaring dua kondisi pertama."""
    response = execute_with_retry(
        supabase.table("reports")
        .select("id")
        .eq("status", STATUS_PENDING)
        .or_("embedding.is.null,extracted_incident_type.is.null,incident_id.is.null")
        .lt("created_at", older_than.isoformat())
        .order("created_at")
        .limit(limit)
    )
    return [row["id"] for row in response.data or []]


def reprocess_reports(
    supabase: Client,
    *,
    dry_run: bool,
    limit: int,
    delay_seconds: float,
    min_age_minutes: int,
    process: Callable[[str], None] = process_report_verification,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> ReprocessSummary:
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=min_age_minutes)
    report_ids = find_unfinished_reports(supabase, limit, cutoff)
    if dry_run:
        return ReprocessSummary(tuple(report_ids), processed=0, dry_run=True)

    for index, report_id in enumerate(report_ids):
        if index > 0 and delay_seconds > 0:
            sleep(delay_seconds)  # jaga kuota free tier Gemini
        process(report_id)  # tidak pernah melempar: kegagalan dicatat di dalamnya
    return ReprocessSummary(tuple(report_ids), processed=len(report_ids), dry_run=False)
