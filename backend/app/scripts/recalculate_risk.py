"""CLI Risk Prediction Agent: hitung ulang skor DASAR kerawanan (REQ-F-020/022).

Dipakai untuk (1) mengisi `risk_scores` pertama kali dari seed data, dan
(2) penjadwalan berkala (cron/scheduler platform) supaya bobot umur kejadian
tetap segar walau tidak ada laporan baru. Pengali musim (jelang/selama Ramadan)
TIDAK ikut tersimpan: ia diterapkan saat skor dibaca, jadi pergantian musim tidak
lagi butuh hitung ulang. Pemicu otomatis setelah insiden terverifikasi ada di
app/agents/verify_agent.py.

Jalankan dari folder backend/, dengan .env terisi SUPABASE_URL dan
SUPABASE_SERVICE_ROLE_KEY:

    python -m app.scripts.recalculate_risk                       # hitung & simpan
    python -m app.scripts.recalculate_risk --dry-run             # hanya tampilkan
    python -m app.scripts.recalculate_risk --dry-run --as-of 2027-01-30
    python -m app.scripts.recalculate_risk --allow-empty         # izinkan mengosongkan risk_scores

`--as-of` sengaja hanya boleh bersama `--dry-run`: skor tersimpan harus selalu
mencerminkan HARI INI, bukan tanggal what-if (hanya memengaruhi bobot umur kejadian).

PENGAMAN: bila hasil perhitungan kosong, skor lama dipertahankan (exit code 2) kecuali
`--allow-empty` — supaya bacaan keliru tidak menghapus seluruh peta kerawanan publik.
"""

import argparse
import logging
import sys
from datetime import date, datetime, time

from app.agents.risk_agent import WIB, recalculate_risk_scores
from app.core.safe_log import safe_error_summary

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# httpx/httpcore log tiap request di level INFO termasuk URL lengkap; redam.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hitung ulang skor kerawanan (Risk Prediction Agent).")
    parser.add_argument("--dry-run", action="store_true", help="hitung & tampilkan, tanpa menulis ke risk_scores")
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="izinkan menyimpan hasil KOSONG (menghapus semua skor lama); tanpa ini hasil kosong dibatalkan",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        help="tanggal what-if (YYYY-MM-DD) untuk melihat efek musiman; hanya bersama --dry-run",
    )
    args = parser.parse_args(argv)
    if args.as_of and not args.dry_run:
        parser.error("--as-of hanya boleh bersama --dry-run (skor tersimpan harus mencerminkan hari ini)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    as_of = datetime.combine(args.as_of, time(12, 0), tzinfo=WIB) if args.as_of else None

    try:
        result = recalculate_risk_scores(as_of, persist=not args.dry_run, allow_empty=args.allow_empty)
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1), tanpa data mentah
        logger.error("Perhitungan skor kerawanan GAGAL: %s", safe_error_summary(exc))
        return 1

    if result.blocked_empty:
        logger.warning(
            "Hasil perhitungan KOSONG: skor lama DIPERTAHANKAN (%d insiden dinilai, %d tanpa koordinat). "
            "Pakai --allow-empty bila memang ingin mengosongkan risk_scores.",
            result.incidents_used,
            result.incidents_skipped_without_coordinates,
        )
        return 2

    if not result.names_resolved:
        logger.warning("Nama wilayah (place_name) TIDAK diperbarui: data areas tak terbaca/kosong (jalankan load_areas).")

    mode = "DRY RUN (tidak disimpan)" if args.dry_run else "disimpan ke risk_scores"
    logger.info(
        "%s | %d insiden dipakai, %d dilewati (tanpa koordinat)",
        mode,
        result.incidents_used,
        result.incidents_skipped_without_coordinates,
    )
    for row in sorted(result.rows, key=lambda r: r.risk_score, reverse=True):
        logger.info(
            "  %-22s %-10s skor=%-5.2f %-7s n=%d  %s",
            row.area_name,
            row.time_bucket,
            row.risk_score,
            row.risk_level,
            row.contributing_incident_count,
            row.place_name or "(tanpa kecamatan dekat)",
        )
    if not args.dry_run:
        logger.info("Selesai: %d baris di-upsert, %d baris usang dihapus.", result.upserted, result.deleted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
