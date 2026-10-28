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
    """Titik yang BENAR-BENAR dipakai untuk rute. `place_name` membiarkan pengguna mengecek hasil
    geocoding nama tempat, yang di Indonesia kasar: nama kecamatan/desa bila reverse geocoding
    berhasil, selain itu teks yang pengguna ketik sendiri atau label sel grid netral — sehingga
    selalu terisi pada pemeriksaan yang berhasil."""

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


class AlternativeRouteOut(BaseModel):
    """Ringkasan satu rute alternatif Mapbox, dinilai dengan aturan yang sama dengan rute utama.
    `is_lowest_risk` = jelas lebih rendah risikonya dari rute utama DAN dari alternatif lain
    (level lebih rendah, atau level sama dengan skor tertinggi lebih rendah); alternatif tanpa
    data sama sekali tidak pernah ditandai. Bandingkan juga `data_coverage` tiap rute."""

    risk_level: Literal["aman", "waspada", "berisiko_tinggi"]
    max_risk_score: float
    distance_km: float
    duration_minutes: int
    data_coverage: float
    data_limited: bool
    is_lowest_risk: bool


class RouteCheckOut(BaseModel):
    """Hasil Cek Rute Aman (REQ-F-030/031/032).

    `risk_level` adalah indikator sederhana (REQ-F-031) dari paparan area sedang/tinggi
    yang dilintasi (aturannya di docstring app/agents/route_agent.py). `areas_to_avoid`
    (REQ-F-032) berisi area berisiko TINGGI yang dilintasi; `areas_to_watch` berisi area
    berisiko sedang (bisa terisi walau status "aman": satu sel sedang tunggal tidak cukup untuk
    "waspada"). "aman" berarti tidak ada paparan yang memenuhi syarat TERCATAT, bukan jaminan:
    `data_coverage` (0..1) = `areas_with_data` / `areas_checked`, `data_limited` true bila datanya
    tidak ada/terlalu sedikit (lalu `data_note` menjelaskan). `location_notes` memuat catatan bila
    geocoding titik diragukan. `alternatives` = ringkasan rute alternatif;
    `safer_alternative_available` true bila salah satunya ditandai `is_lowest_risk`.
    `narrative` (penjelasan Gemini) opsional; None bukan error.
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
    data_coverage: float = 0.0
    data_limited: bool = False
    data_note: str | None = None
    location_notes: list[str] = Field(default_factory=list)
    alternatives: list[AlternativeRouteOut] = Field(default_factory=list)
    safer_alternative_available: bool = False
    narrative: str | None = None
