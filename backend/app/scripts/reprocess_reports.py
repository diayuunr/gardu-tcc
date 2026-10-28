"""CLI Verification Agent: proses ulang laporan yang verifikasinya belum tuntas (REQ-NF-110).

Laporan mentah selalu tersimpan lebih dulu; kalau AI/koneksi gagal di tengah
verifikasi, laporan tetap berstatus `menunggu_verifikasi` tanpa `embedding`,
tanpa `extracted_incident_type`, atau tanpa `incident_id` (belum diklasterkan).
Skrip ini mengambil laporan-laporan itu lalu menjalankan ulang
`process_report_verification` satu per satu.

IDEMPOTEN: `process_report_verification` melewati laporan yang statusnya sudah
berubah, tidak mengklasterkan ulang laporan yang sudah punya `incident_id`, dan
tidak meminta ulang jenis kejadian yang sudah ada. Menjalankan skrip dua kali
tidak membuat insiden ganda; laporan yang sudah lengkap tidak diambil lagi.

Hanya laporan yang dibuat lebih dari `reprocess_min_age_minutes` menit lalu yang
diambil, supaya tidak berbenturan dengan background task POST /reports yang
masih berjalan.

Jalankan dari folder backend/, dengan .env terisi SUPABASE_URL dan
SUPABASE_SERVICE_ROLE_KEY (dan GEMINI_API_KEY untuk ekstraksi/embedding):

    python -m app.scripts.reprocess_reports --dry-run     # hanya tampilkan jumlahnya
    python -m app.scripts.reprocess_reports               # proses ulang
    python -m app.scripts.reprocess_reports --limit 50 --delay-seconds 6

Log hanya memuat jumlah dan id laporan (UUID), tidak pernah teks laporan.
"""

import argparse
import logging
import sys

from app.agents.reprocess import ReprocessSummary, find_unfinished_reports, reprocess_reports  # noqa: F401 - diekspor ulang
from app.core.config import get_settings
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# httpx/httpcore log tiap request di level INFO termasuk URL lengkap; redam.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Proses ulang laporan yang verifikasinya belum tuntas.")
    parser.add_argument("--dry-run", action="store_true", help="hanya tampilkan laporan yang akan diproses")
    parser.add_argument(
        "--limit", type=int, default=settings.reprocess_batch_limit, help="maksimum laporan per kali jalan"
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=settings.reprocess_delay_seconds,
        help="jeda antar laporan (menjaga kuota Gemini)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()

    try:
        summary = reprocess_reports(
            get_supabase(),
            dry_run=args.dry_run,
            limit=args.limit,
            delay_seconds=args.delay_seconds,
            min_age_minutes=settings.reprocess_min_age_minutes,
        )
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1), tanpa data mentah
        logger.error("Pemrosesan ulang laporan GAGAL: %s", safe_error_summary(exc))
        return 1

    if summary.dry_run:
        logger.info("DRY RUN: %d laporan akan diproses ulang (tidak ada yang diubah).", summary.found)
        for report_id in summary.report_ids:
            logger.info("  %s", report_id)
    else:
        logger.info("Selesai: %d laporan diproses ulang.", summary.processed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
