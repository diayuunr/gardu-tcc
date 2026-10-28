import re
import unicodedata
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.areas import KODE_REGEX
from app.core.privacy import mask_personal_data
from app.core.timeutil import to_wib

_MAX_JALAN_LENGTH = 200
_EMAIL_PATTERN = re.compile(r"\S+@\S+\.\S+")
_PHONE_PATTERN = re.compile(r"\d[\d\s().-]{7,}\d")  # >= 9 digit berurutan (nomor telepon)


class ReportStatus(str, Enum):
    """Status laporan (REQ-F-005). Tidak ada status yang menyingkap identitas pelapor."""

    MENUNGGU_VERIFIKASI = "menunggu_verifikasi"
    TERVERIFIKASI = "terverifikasi"
    DITANDAI_DUPLIKAT = "ditandai_duplikat"
    DITANDAI_HOAKS = "ditandai_hoaks"


# Kategori jenis kejadian pilihan pelapor (dropdown). Nilai TETAP = kosakata kategori insiden (CATEGORY_RULES di
# app/agents/incident_index.py + "lainnya") dan CHECK di migrasi 20260924000000; test menjaga ketiganya selaras.
IncidentTypeHint = Literal[
    "klitih",
    "penyerangan",
    "bentrok antar kelompok",
    "begal/penodongan",
    "kejadian mencurigakan",
    "pengrusakan",
    "lainnya",
]


class ReportCreate(BaseModel):
    """Payload laporan warga. Sengaja TIDAK punya field nama/no_hp/email/akun_sosial (REQ-NF-120).

    Lokasi lewat SATU dari dua jalur:
    - berjenjang (disarankan): `kabkota_kode` + `kecamatan_kode` [+ `kelurahan_kode`] [+ `jalan`].
      Hierarki divalidasi ke tabel `areas` di server, dan `location_text` DISUSUN server dari nama
      wilayah (kiriman `location_text` bersamaan dengan kode diabaikan);
    - lama (kompatibel mundur): `location_text` saja.
    `latitude`/`longitude` opsional (titik dari peta); bila kosong, koordinat awal diambil dari
    pusat wilayah terpilih.
    """

    description: str = Field(..., min_length=10, max_length=2000)
    location_text: str | None = Field(default=None, min_length=3, max_length=200)
    kabkota_kode: str | None = Field(default=None, pattern=KODE_REGEX)
    kecamatan_kode: str | None = Field(default=None, pattern=KODE_REGEX)
    kelurahan_kode: str | None = Field(default=None, pattern=KODE_REGEX)
    jalan: str | None = Field(default=None, max_length=400)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    occurred_at: datetime
    # Kategori dari dropdown (opsional). Disimpan terpisah dari `description` (tidak ikut embedding) dan hanya
    # dipakai sebagai petunjuk bila ekstraksi Gemini gagal.
    incident_type_hint: IncidentTypeHint | None = None

    @field_validator("description", "location_text")
    @classmethod
    def tidak_boleh_kosong_dan_samarkan_data_pribadi(cls, value: str | None) -> str | None:
        """Teks dirapikan, lalu email/NIK/nomor telepon DISAMARKAN (bukan ditolak; REQ-NF-120)
        sebelum apa pun disimpan atau dikirim ke embedding/Gemini. Nomor polisi tidak disamarkan
        (informasi kejadian yang sah) — lihat app/core/privacy.py."""
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Tidak boleh kosong atau hanya berisi spasi")
        return mask_personal_data(stripped)

    @field_validator("jalan")
    @classmethod
    def bersihkan_jalan(cls, value: str | None) -> str | None:
        """Karakter kontrol dibuang, spasi dirapikan; kosong -> None; maks 200 karakter SETELAH
        dibersihkan. Teks yang tampak seperti email/nomor telepon ditolak (REQ-NF-120)."""
        if value is None:
            return None
        cleaned = " ".join("".join(ch for ch in value if unicodedata.category(ch)[0] != "C" or ch.isspace()).split())
        if not cleaned:
            return None
        if len(cleaned) > _MAX_JALAN_LENGTH:
            raise ValueError(f"Nama jalan atau patokan maksimal {_MAX_JALAN_LENGTH} karakter")
        if _EMAIL_PATTERN.search(cleaned) or _PHONE_PATTERN.search(cleaned):
            raise ValueError("Nama jalan atau patokan tidak boleh berisi email atau nomor telepon")
        return cleaned

    @model_validator(mode="after")
    def lokasi_berjenjang_atau_teks(self) -> "ReportCreate":
        has_region = any((self.kabkota_kode, self.kecamatan_kode, self.kelurahan_kode))
        if has_region:
            if not (self.kabkota_kode and self.kecamatan_kode):
                raise ValueError("Pilih kabupaten/kota dan kecamatan terlebih dahulu")
            # Teks dari klien tidak dipercaya: lokasi disusun ulang server dari tabel areas.
            self.location_text = None
        else:
            if self.jalan:
                raise ValueError("Nama jalan harus disertai pilihan kabupaten/kota dan kecamatan")
            if not self.location_text:
                raise ValueError("Isi lokasi kejadian: pilih kabupaten/kota dan kecamatan, atau tulis lokasinya")
        return self

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


# ----------------------------------------------------------- daftar & statistik publik (REQ-F-042)


class PublicReportOut(BaseModel):
    """Satu laporan di daftar PUBLIK: sengaja tanpa deskripsi, jalan, koordinat, teks lokasi lengkap, atau UUID.

    `occurred_at` dibulatkan ke bawah per JAM (WIB) supaya tidak menjadi sidik jari pelapor."""

    nomor: str  # id pendek, mis. "GRD-000123"
    status: Literal["menunggu_verifikasi", "terverifikasi"]
    occurred_at: datetime
    wilayah: str  # kecamatan, mis. "Kec. Depok, Kabupaten Sleman"
    jenis: str  # kategori tetap (lihat IncidentTypeHint)


class PublicReportsOut(BaseModel):
    total: int  # jumlah laporan yang dapat ditampilkan (tidak termasuk yang ditandai duplikat/hoaks)
    limit: int
    offset: int
    items: list[PublicReportOut]


class ReportStatusCounts(BaseModel):
    menunggu_verifikasi: int
    terverifikasi: int
    ditandai_duplikat: int
    ditandai_hoaks: int


class ReportStatsOut(BaseModel):
    """Statistik agregat untuk landing. Hanya angka; tidak ada isi laporan."""

    total_reports: int
    reports_by_status: ReportStatusCounts
    verified_incidents: int  # semua insiden berstatus terverifikasi
    verified_incidents_from_reports: int  # hanya yang bukan data seed (hasil laporan warga)
    historical_incidents: int  # data seed historis (pemberitaan); berstatus "baru" tetapi ikut skor kerawanan
