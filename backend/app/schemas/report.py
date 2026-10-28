from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ReportStatus(str, Enum):
    """Status laporan (REQ-F-005). Tidak ada status yang menyingkap identitas pelapor."""

    MENUNGGU_VERIFIKASI = "menunggu_verifikasi"
    TERVERIFIKASI = "terverifikasi"
    DITANDAI_DUPLIKAT = "ditandai_duplikat"
    DITANDAI_HOAKS = "ditandai_hoaks"


class ReportCreate(BaseModel):
    """Payload laporan warga. Sengaja TIDAK punya field nama/no_hp/email/akun_sosial (REQ-NF-120)."""

    description: str = Field(..., min_length=10, max_length=2000)
    location_text: str = Field(..., min_length=3, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    occurred_at: datetime

    @field_validator("description", "location_text")
    @classmethod
    def tidak_boleh_kosong(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Tidak boleh kosong atau hanya berisi spasi")
        return stripped

    @field_validator("occurred_at")
    @classmethod
    def waktu_tidak_boleh_jauh_di_masa_depan(cls, value: datetime) -> datetime:
        now = datetime.now(timezone.utc)
        compare = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if compare > now + timedelta(minutes=5):
            raise ValueError("Waktu kejadian tidak boleh di masa depan")
        return value


class ReportOut(BaseModel):
    """Respons setelah laporan tersimpan (REQ-NF-100: konfirmasi cepat)."""

    id: str
    status: ReportStatus
    created_at: datetime
