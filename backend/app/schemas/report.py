from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.core.timeutil import to_wib


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
    def normalisasi_zona_waktu_dan_tolak_masa_depan(cls, value: datetime) -> datetime:
        """Waktu tanpa zona = waktu lokal pengguna (WIB), sama seperti `to_wib` di
        Risk Prediction Agent & Safe Route Advisor — supaya jam 02:00 tetap bucket
        `dini_hari` dan tidak bergeser 7 jam. Hasilnya selalu timezone-aware, dan
        pengecekan "bukan masa depan" memakai nilai yang SUDAH dinormalisasi itu."""
        normalized = to_wib(value)
        if normalized > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("Waktu kejadian tidak boleh di masa depan")
        return normalized


class ReportOut(BaseModel):
    """Respons setelah laporan tersimpan (REQ-NF-100: konfirmasi cepat)."""

    id: str
    status: ReportStatus
    created_at: datetime
