from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.report import ReportStatus


class ModeratorOut(BaseModel):
    display_name: str


class ModerationReportOut(BaseModel):
    """Satu laporan untuk moderator (terautentikasi). Memuat isi laporan karena moderator perlu menilainya;
    TIDAK memuat koordinat, IP, atau identitas apa pun."""

    id: str
    nomor: str
    status: ReportStatus
    flagged_reason: str | None
    moderation_decision: Literal["disetujui", "ditolak"] | None
    description: str
    location_text: str
    occurred_at: datetime
    created_at: datetime
    extracted_incident_type: str | None
    incident_type_hint: str | None
    incident_id: str | None


class ModerationListOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ModerationReportOut]


class ModerationDecisionIn(BaseModel):
    """Status tujuan: `terverifikasi` (setujui), `ditandai_hoaks` (tolak), `menunggu_verifikasi` (kembalikan)."""

    status: Literal["terverifikasi", "ditandai_hoaks", "menunggu_verifikasi"]


class ModerationResultOut(BaseModel):
    id: str
    status: ReportStatus
    changed: bool  # False bila laporan sudah berada pada keputusan itu (idempoten)
    incident_status: Literal["baru", "terverifikasi"] | None  # None: laporan tidak (lagi) terhubung ke insiden
    scores_refresh_scheduled: bool
