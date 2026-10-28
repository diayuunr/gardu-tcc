from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TimeBucket = Literal["dini_hari", "pagi", "siang", "sore", "malam"]

# Batas wajar waktu berangkat: mencegah nilai absurd (mis. tahun 9999 yang meluap
# saat ditambah durasi) — bukan aturan bisnis yang ketat.
_MAX_DEPARTURE_PAST = timedelta(days=1)
_MAX_DEPARTURE_FUTURE = timedelta(days=30)


class PlaceInput(BaseModel):
    """Satu titik rute: teks lokasi ATAU koordinat (mis. dari GPS peramban).

    Koordinat menang bila keduanya diisi. Hanya berisi lokasi yang diketik/dipilih
    pengguna untuk RUTE-nya sendiri — tidak disimpan, tidak ada identitas apa pun.
    """

    text: str | None = Field(default=None, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("text")
    @classmethod
    def rapikan_teks(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = " ".join(value.split())
        if not stripped:
            return None
        if len(stripped) < 2:
            raise ValueError("Teks lokasi minimal 2 karakter")
        return stripped

    @model_validator(mode="after")
    def wajib_teks_atau_koordinat_lengkap(self) -> "PlaceInput":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude dan longitude harus diisi bersamaan")
        if self.latitude is None and self.text is None:
            raise ValueError("Isi teks lokasi atau koordinat")
        return self


class RouteCheckRequest(BaseModel):
    """Masukan Cek Rute Aman (SRS: titik asal, titik tujuan, waktu berangkat)."""

    origin: PlaceInput
    destination: PlaceInput
    departure_time: datetime | None = Field(
        default=None, description="Waktu berangkat; kosong = sekarang. Tanpa zona waktu dianggap WIB."
    )

    @field_validator("departure_time")
    @classmethod
    def waktu_berangkat_wajar(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        now = datetime.now(timezone.utc)
        compare = value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=7)))
        if compare < now - _MAX_DEPARTURE_PAST or compare > now + _MAX_DEPARTURE_FUTURE:
            raise ValueError("Waktu berangkat harus antara 1 hari lalu dan 30 hari ke depan")
        return value


class PointOut(BaseModel):
    """Titik yang BENAR-BENAR dipakai untuk rute. `place_name` (kecamatan/desa, best-effort)
    membiarkan pengguna mengecek hasil geocoding nama tempat, yang di Indonesia kasar."""

    latitude: float
    longitude: float
    place_name: str | None = None


class FlaggedAreaOut(BaseModel):
    """Area berskor sedang/tinggi yang dilintasi rute. Koordinat = pusat sel grid publik,
    `place_name` = nama tingkat kecamatan/desa (bukan alamat) — REQ-F-042."""

    area_name: str
    place_name: str | None
    latitude: float
    longitude: float
    time_bucket: TimeBucket
    risk_score: float
    risk_level: Literal["sedang", "tinggi"]


class RouteCheckOut(BaseModel):
    """Hasil Cek Rute Aman (REQ-F-030/031/032).

    `risk_level` adalah indikator sederhana (REQ-F-031). `areas_to_avoid` (REQ-F-032)
    berisi area berisiko TINGGI yang dilintasi — terisi bila dan hanya bila rute
    berisiko_tinggi; `areas_to_watch` berisi area berisiko sedang. "aman" berarti
    tidak ada area sedang/tinggi TERCATAT, bukan jaminan: lihat `areas_with_data`
    vs `areas_checked` untuk cakupan datanya. `narrative` (penjelasan Gemini)
    opsional; None bukan error.
    """

    risk_level: Literal["aman", "waspada", "berisiko_tinggi"]
    max_risk_score: float
    areas_to_avoid: list[FlaggedAreaOut]
    areas_to_watch: list[FlaggedAreaOut]
    areas_checked: int
    areas_with_data: int
    origin: PointOut
    destination: PointOut
    distance_km: float
    duration_minutes: int
    departure_time: datetime
    time_buckets: list[TimeBucket]
    narrative: str | None = None
