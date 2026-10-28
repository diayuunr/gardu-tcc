"""Endpoint INTERNAL untuk penjadwal (Railway cron, GitHub Actions, dsb.) — bukan untuk browser/frontend.

Dilindungi header `X-Internal-Token` = env `INTERNAL_API_TOKEN` (kosong = endpoint mati, menjawab 404). Pekerjaan
berjalan di latar belakang dan responsnya `202` segera, jadi pemanggil cron tidak perlu menunggu proses AI.
Skrip CLI (`python -m app.scripts.reprocess_reports` / `recalculate_risk`) tetap tersedia dan memakai logika yang sama."""

import logging
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel
from supabase import Client

from app.agents.reprocess import find_unfinished_reports, reprocess_reports
from app.agents.risk_agent import refresh_risk_scores_safely
from app.core.auth import require_internal_token
from app.core.config import get_settings
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_token)],
    responses={
        401: {"description": "X-Internal-Token salah atau hilang."},
        404: {"description": "Endpoint internal dimatikan (INTERNAL_API_TOKEN kosong)."},
    },
)

_reprocess_lock = threading.Lock()  # satu proses ulang dalam satu waktu (kuota Gemini terbatas)


class ReprocessOut(BaseModel):
    found: int  # laporan yatim yang ditemukan
    queued: int  # yang dijadwalkan diproses di latar belakang (0 pada dry_run)
    dry_run: bool


class AcceptedOut(BaseModel):
    accepted: bool = True


def _run_reprocess(supabase: Client, limit: int) -> None:
    """Dijalankan di latar belakang; kunci dipegang sejak endpoint menerima permintaan sampai selesai."""
    try:
        settings = get_settings()
        summary = reprocess_reports(
            supabase,
            dry_run=False,
            limit=limit,
            delay_seconds=settings.reprocess_delay_seconds,
            min_age_minutes=settings.reprocess_min_age_minutes,
        )
        logger.info("Proses ulang laporan (job internal) selesai: %d laporan", summary.processed)
    except Exception as exc:  # noqa: BLE001 - job latar belakang tidak boleh melempar
        logger.error("Proses ulang laporan (job internal) GAGAL: %s", safe_error_summary(exc))
    finally:
        _reprocess_lock.release()


@router.post("/reprocess", response_model=ReprocessOut, status_code=status.HTTP_202_ACCEPTED, summary="Proses ulang laporan yatim")
def reprocess(
    background_tasks: BackgroundTasks,
    limit: int = Query(None, ge=1, description="Maks laporan per panggilan (dibatasi INTERNAL_REPROCESS_MAX_BATCH)."),
    dry_run: bool = Query(False, description="Hanya hitung laporan yang akan diproses."),
    supabase: Client = Depends(get_supabase),
) -> ReprocessOut:
    """Mengambil laporan `menunggu_verifikasi` yang belum tuntas (tanpa embedding / jenis kejadian / insiden dan sudah
    lebih tua dari `REPROCESS_MIN_AGE_MINUTES`), lalu memprosesnya satu per satu di latar belakang. Idempoten.
    `409` bila proses ulang sebelumnya masih berjalan."""
    settings = get_settings()
    size = min(limit or settings.internal_reprocess_max_batch, settings.internal_reprocess_max_batch)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.reprocess_min_age_minutes)
    try:
        found = len(find_unfinished_reports(supabase, size, cutoff))
    except Exception as exc:  # noqa: BLE001
        logger.error("Gagal mencari laporan yatim: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Data laporan sementara tidak dapat diambil.") from None
    if dry_run or found == 0:
        return ReprocessOut(found=found, queued=0, dry_run=dry_run)
    if not _reprocess_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "Proses ulang sebelumnya masih berjalan.")
    background_tasks.add_task(_run_reprocess, supabase, size)
    return ReprocessOut(found=found, queued=found, dry_run=False)


@router.post("/recalculate-risk", response_model=AcceptedOut, status_code=status.HTTP_202_ACCEPTED, summary="Hitung ulang skor kerawanan")
def recalculate_risk(background_tasks: BackgroundTasks) -> AcceptedOut:
    """Menghitung ulang skor DASAR kerawanan di latar belakang (menyegarkan bobot umur kejadian walau tidak ada laporan
    baru). Panggilan yang bertumpuk digabung otomatis (`refresh_risk_scores_safely`), jadi aman dipanggil berkala."""
    background_tasks.add_task(refresh_risk_scores_safely)
    return AcceptedOut()
