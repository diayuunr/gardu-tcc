from datetime import datetime
from typing import Literal

from pydantic import BaseModel

TimeBucket = Literal["dini_hari", "pagi", "siang", "sore", "malam"]


class RiskCellOut(BaseModel):
    """Satu sel di heatmap (REQ-F-040). `label` = nama untuk ditampilkan: `place_name` ("Kec. X") atau
    label grid `area_name` bila tak ada kecamatan dekat. Koordinat = pusat sel grid publik, label area
    netral, dan angka agregat saja — tanpa teks lokasi laporan atau identitas siapa pun
    (REQ-F-042, REQ-NF-121)."""

    area_name: str
    place_name: str | None = None
    label: str
    latitude: float
    longitude: float
    risk_score: float
    risk_level: Literal["rendah", "sedang", "tinggi"]
    contributing_incident_count: int


class RegionRiskOut(BaseModel):
    """Ringkasan skor satu kecamatan (agregat dari sel-selnya). Tanpa koordinat sel, teks lokasi,
    atau data individu (REQ-F-042)."""

    kecamatan_kode: str
    place_name: str
    label: str
    risk_score: float
    risk_level: Literal["rendah", "sedang", "tinggi"]
    cell_count: int
    incident_count: int


class RiskSummaryOut(BaseModel):
    """Ringkasan per kecamatan untuk satu bucket jam, urut skor tertinggi. `unassigned_cell_count` =
    sel yang tidak punya kecamatan dekat (tidak masuk daftar). `updated_at` = perhitungan terbaru."""

    time_bucket: TimeBucket
    regions: list[RegionRiskOut]
    unassigned_cell_count: int
    updated_at: datetime | None


class RiskHeatmapOut(BaseModel):
    """Semua sel skor untuk satu bucket jam. `updated_at` = waktu perhitungan terbaru
    di antara sel-sel itu (None bila belum ada sel)."""

    time_bucket: TimeBucket
    cells: list[RiskCellOut]
    updated_at: datetime | None


class RiskScoreOut(BaseModel):
    """Skor kerawanan untuk satu area & rentang waktu (REQ-F-020).

    `area_name` = label grid netral (kunci teknis); `place_name` = nama wilayah nyata ("Kec. X", kecamatan
    terdekat) bila sudah dihitung; `label` = yang SEBAIKNYA ditampilkan (place_name, atau area_name bila
    tak ada kecamatan dekat).

    Hanya berisi label area netral dan angka agregat — tidak ada teks lokasi
    laporan, koordinat insiden asli, maupun identitas siapa pun (REQ-F-042).
    `has_data=False` artinya belum ada data untuk sel/waktu itu, BUKAN jaminan aman.
    `narrative` = penjelasan 1-2 kalimat dari Gemini. Hanya terisi bila klien
    meminta `include_narrative=true`, skornya sedang/tinggi, dan Gemini tersedia;
    None bukan error — angka skor tetap valid.
    """

    area_name: str
    place_name: str | None = None
    label: str
    time_bucket: Literal["dini_hari", "pagi", "siang", "sore", "malam"]
    risk_score: float
    risk_level: Literal["rendah", "sedang", "tinggi"]
    contributing_incident_count: int
    has_data: bool
    narrative: str | None = None
