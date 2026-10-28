import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from supabase import Client

from app.agents.moderation import (
    ReportNotFound,
    apply_decision,
    list_reports,
    public_number_label,
)
from app.agents.risk_agent import refresh_risk_scores_safely
from app.core.auth import Moderator, get_current_moderator
from app.core.config import get_settings
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.moderation import (
    ModerationDecisionIn,
    ModerationListOut,
    ModerationReportOut,
    ModerationResultOut,
    ModeratorOut,
)
from app.schemas.report import ReportStatus

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/moderation",
    tags=["moderation"],
    responses={
        401: {"description": "Token Supabase Auth hilang, tidak valid, atau kedaluwarsa."},
        403: {"description": "Akun tidak terdaftar sebagai moderator."},
    },
)

# Bawaan antrean tinjauan: yang butuh mata manusia (menunggu + ditandai otomatis).
_DEFAULT_REVIEW_STATUSES = [
    ReportStatus.MENUNGGU_VERIFIKASI,
    ReportStatus.DITANDAI_DUPLIKAT,
    ReportStatus.DITANDAI_HOAKS,
]


def _to_out(row: dict) -> ModerationReportOut:
    return ModerationReportOut(
        id=row["id"],
        nomor=public_number_label(row.get("public_number")),
        status=row["status"],
        flagged_reason=row.get("flagged_reason"),
        moderation_decision=row.get("moderation_decision"),
        description=row["description"],
        location_text=row["location_text"],
        occurred_at=row["occurred_at"],
        created_at=row["created_at"],
        extracted_incident_type=row.get("extracted_incident_type"),
        incident_type_hint=row.get("incident_type_hint"),
        incident_id=row.get("incident_id"),
    )


@router.get("/me", response_model=ModeratorOut, summary="Periksa sesi moderator")
def me(moderator: Moderator = Depends(get_current_moderator)) -> ModeratorOut:
    """Memastikan token valid dan akun terdaftar sebagai moderator (untuk gerbang halaman panel)."""
    return ModeratorOut(display_name=moderator.display_name)


@router.get("/reports", response_model=ModerationListOut, summary="Antrean laporan untuk ditinjau")
def list_moderation_reports(
    statuses: Annotated[
        list[ReportStatus] | None,
        Query(alias="status", description="Filter status (boleh diulang). Bawaan: menunggu + ditandai duplikat/hoaks."),
    ] = None,
    limit: int = Query(20, ge=1, description="Jumlah per halaman (maks sesuai MODERATION_MAX_PAGE_SIZE, 100)."),
    offset: int = Query(0, ge=0),
    _moderator: Moderator = Depends(get_current_moderator),
    supabase: Client = Depends(get_supabase),
) -> ModerationListOut:
    """Laporan terbaru dulu, lengkap dengan `flagged_reason` (alasan penandaan otomatis) dan keputusan moderator
    sebelumnya. Hanya moderator yang dapat melihat isi laporan; koordinat tidak disertakan."""
    limit = min(limit, get_settings().moderation_max_page_size)
    wanted = [s.value for s in (statuses or _DEFAULT_REVIEW_STATUSES)]
    try:
        rows, total = list_reports(supabase, wanted, limit, offset)
    except Exception as exc:  # noqa: BLE001
        logger.error("Gagal memuat antrean moderasi: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Data laporan sementara tidak dapat diambil.") from None
    return ModerationListOut(total=total, limit=limit, offset=offset, items=[_to_out(row) for row in rows])


@router.patch("/reports/{report_id}", response_model=ModerationResultOut, summary="Setujui / tolak / kembalikan laporan")
def decide_report(
    report_id: UUID,
    decision: ModerationDecisionIn,
    background_tasks: BackgroundTasks,
    moderator: Moderator = Depends(get_current_moderator),
    supabase: Client = Depends(get_supabase),
) -> ModerationResultOut:
    """`terverifikasi` = setujui, `ditandai_hoaks` = tolak, `menunggu_verifikasi` = kembalikan ke antrean.

    Insiden yang terdampak disinkronkan (dinaikkan/diturunkan/dihapus) dan, bila status terverifikasinya berubah,
    skor kerawanan dihitung ulang di latar belakang. Mengulang keputusan yang sama aman (idempoten)."""
    try:
        outcome = apply_decision(supabase, str(report_id), decision.status, moderator.id)
    except ReportNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak ditemukan.") from None
    except Exception as exc:  # noqa: BLE001 - kegagalan DB: pesan aman, tanpa isi baris
        logger.error("Keputusan moderasi gagal diterapkan: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Keputusan gagal disimpan, silakan coba lagi.") from None

    if outcome.refresh_scores:
        background_tasks.add_task(refresh_risk_scores_safely)
    logger.info("Moderasi: laporan %s -> %s (moderator %s)", report_id, outcome.report_status, moderator.id)
    return ModerationResultOut(
        id=str(report_id),
        status=outcome.report_status,
        changed=outcome.changed,
        incident_status=outcome.incident_status,
        scores_refresh_scheduled=outcome.refresh_scores,
    )
