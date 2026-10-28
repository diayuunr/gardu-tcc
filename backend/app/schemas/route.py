from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config import get_settings

TimeBucket = Literal["dini_hari", "pagi", "siang", "sore", "malam"]

# Batas atas waktu berangkat: mencegah nilai absurd (mis. tahun 9999 yang meluap saat ditambah durasi).
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
        """Waktu tanpa zona = WIB. Berangkat di masa lalu lebih dari `route_departure_grace_minutes` (5 mnt)
        ditolak: rute yang sudah lewat tak punya arti untuk peringatan dini, dan jam yang salah akan memilih
        bucket & musim yang salah. Maksimal 30 hari ke depan."""
        if value is None:
            return None
        now = datetime.now(timezone.utc)
        compare = value if value.tzinfo else value.replace(tzinfo=timezone(timedelta(hours=7)))
        grace = timedelta(minutes=get_settings().route_departure_grace_minutes)
        if compare < now - grace:
            raise ValueError("Waktu berangkat tidak boleh di masa lalu")
        if compare > now + _MAX_DEPARTURE_FUTURE:
            raise ValueError("Waktu berangkat maksimal 30 hari ke depan")
        return value


class PointOut(BaseModel):
    """Titik yang BENAR-BENAR dipakai untuk rute. `place_name` membiarkan pengguna mengecek hasil
    geocoding nama tempat, yang di Indonesia kasar: nama kecamatan/desa bila reverse geocoding
    berhasil, selain itu teks yang pengguna ketik sendiri atau label sel grid netral — sehingga
    selalu terisi pada pemeriksaan yang berhasil."""

    latitude: float
    longitude: float
    place_name: str | None = None


class GeoLineStringOut(BaseModel):
    """Garis GeoJSON siap pakai untuk Mapbox GL / Leaflet (GeoJSON). URUTAN KOORDINAT `[bujur, lintang]`
    (longitude, latitude), BUKAN [lintang, bujur]. Sudah dijarangkan (toleransi `route_geometry_tolerance_meters`)."""

    type: Literal["LineString"] = "LineString"
    coordinates: list[list[float]]


class SegmentOut(BaseModel):
    """Satu ruas jalan pada rute (langkah berurutan bernama sama). HANYA agregat: tidak ada koordinat atau
    deskripsi insiden individual; `geometry` adalah garis RUTE ruas itu (bukan lokasi insiden)."""

    index: int
    road_name: str
    place_name: str | None
    start_km: float
    end_km: float
    length_m: int
    risk_level: Literal["rendah", "sedang", "tinggi"]
    risk_score: float
    incident_count: int
    dominant_category: str | None
    incident_hours: dict[str, int]
    has_nearby_data: bool
    peak_time_bucket: TimeBucket
    geometry: GeoLineStringOut


class RouteSummaryOut(BaseModel):
    status: Literal["aman", "waspada", "berisiko_tinggi"]
    max_risk_score: float
    distance_km: float
    duration_minutes: int
    data_coverage: float
    data_limited: bool
    high_exposure_m: int
    medium_exposure_m: int
    incident_count: int
    time_buckets: list[TimeBucket]


class FlaggedAreaOut(BaseModel):
    """Ruas jalan berlevel sedang/tinggi yang dilintasi (bentuk lama dipertahankan untuk frontend).
    `area_name` = nama jalan, `place_name` = "Kec. X", `label` = teks tampil, koordinat = titik di JALUR
    TITIK TENGAH ruas itu di jalur (bukan lokasi insiden, bukan titik puncak skor) — REQ-F-042."""

    area_name: str
    place_name: str | None
    label: str
    latitude: float
    longitude: float
    time_bucket: TimeBucket
    risk_score: float
    risk_level: Literal["sedang", "tinggi"]
    segment_index: int | None = None


class AlternativeRouteOut(BaseModel):
    """Rute alternatif Mapbox, dinilai dengan aturan yang sama dengan rute utama (ringkasan + peta + alasan).
    `is_lowest_risk` = jelas lebih rendah risikonya dari rute utama DAN dari alternatif lain; alternatif tanpa
    data atau datanya tak sebanding tidak pernah ditandai. `extra_minutes` = selisih waktu tempuh (negatif =
    lebih cepat)."""

    risk_level: Literal["aman", "waspada", "berisiko_tinggi"]
    max_risk_score: float
    distance_km: float
    duration_minutes: int
    data_coverage: float
    data_limited: bool
    is_lowest_risk: bool
    extra_minutes: int = 0
    summary: RouteSummaryOut | None = None
    geometry: GeoLineStringOut | None = None
    segments: list[SegmentOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class RouteCheckOut(BaseModel):
    """Hasil Cek Rute Aman (REQ-F-030/031/032).

    Ringkas: `summary` (status, skor, jarak, durasi, cakupan data), `geometry` (garis rute GeoJSON, urutan
    [bujur, lintang]), `segments` (ruas jalan berurutan beserta level & agregat kejadian untuk mewarnai garis),
    `reasons` (alasan netral berbahasa Indonesia), dan `alternatives` (rute alternatif dengan struktur serupa).
    `recommended_route`: 0 = rute utama paling rendah risikonya, i>=1 = alternatif ke-i (1-based) yang disarankan.

    Field lama dipertahankan: `risk_level`, `max_risk_score`, `areas_to_avoid` (ruas berlevel TINGGI),
    `areas_to_watch` (ruas SEDANG), `areas_checked`/`areas_with_data` (= titik cek / titik berdata),
    `data_coverage`, `data_limited`, `data_note`, `location_notes`, `safer_alternative_available`, `narrative`.
    "aman" berarti tidak ada paparan yang memenuhi syarat DI DATA YANG TERCATAT, bukan jaminan keamanan.
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
    summary: RouteSummaryOut | None = None
    geometry: GeoLineStringOut | None = None
    segments: list[SegmentOut] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    recommended_route: int = 0
    narrative: str | None = None
