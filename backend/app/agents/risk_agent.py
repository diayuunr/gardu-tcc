"""Risk Prediction Agent (REQ-F-020, REQ-F-022, REQ-F-023).

Menghitung skor kerawanan 0-10 per (area, rentang waktu) dari insiden yang
sudah ada di tabel `incidents`, lalu menyimpannya ke `risk_scores` (dibaca
publik oleh Dasbor Peta & Safe Route Advisor).

KEPUTUSAN DESAIN: perhitungan ini DETERMINISTIK dan tidak memanggil LLM.
Skor per area/jam adalah agregasi numerik — LLM tidak menambah akurasi, tapi
membuat hasil tidak reprodusibel (TC-RSK-001 butuh skor konsisten), tidak
bisa dijelaskan rumusnya, dan memakan kuota free tier Gemini (15 request per
menit) untuk pekerjaan yang tidak butuh bahasa alami. Gemini hanya dipakai
di lapisan NARASI terpisah (app/agents/risk_narrator.py) yang MENJELASKAN
angka dari modul ini dan tidak pernah menghitung atau mengubahnya.

Model (SEMUA parameter = asumsi simulasi, bisa disetel lewat env, lihat
app/core/config.py):
- Area   : sel grid ~1 km (`risk_grid_cell_degrees`), diberi label NETRAL dari
           koordinat pusat sel. SENGAJA bukan dari teks lokasi laporan: tabel
           `risk_scores` bisa dibaca publik dan teks lokasi warga bisa berisi
           alamat rumah (REQ-NF-120/REQ-F-042).
- Waktu  : 5 bucket jam WIB: dini_hari 00-05, pagi 05-11, siang 11-15, sore 15-18,
           malam 18-24 (jam selesai eksklusif).
- Bobot  : tiap insiden berbobot 0.5 ** (umur / half-life) — kejadian lama
           tetap dihitung tapi makin kecil pengaruhnya (half-life panjang supaya
           seed data historis 2020-2023 masih berpengaruh, REQ-F-021 cold start).
- Sebaran: insiden juga menyumbang `risk_neighbor_weight` (default 0.25) dari bobotnya
           ke 8 sel tetangga — kejadian di pinggir sel tidak berhenti di garis grid.
           Sel tetangga TANPA insiden sendiri hanya diberi baris skor bila skornya
           >= `risk_neighbor_min_score` (default 1.0): pilihan ini mencegah satu
           insiden tunggal "mengecat" sembilan sel, tetapi tetap menangkap kumpulan
           insiden di perbatasan sel. `contributing_incident_count` hanya menghitung
           insiden DI sel itu sendiri (0 untuk sel yang skornya murni dari tetangga).
- Skor   : DASAR = 10 * (1 - exp(-intensitas / skala)) — jenuh mulus di bawah 10, tanpa
           normalisasi global (satu titik panas tidak menekan area lain). Inilah yang
           disimpan di `risk_scores` (TANPA pengali musim).
- Musim  : pengali Ramadan (jelang/selama, plus tambahan jam sahur/SOTR, REQ-F-023)
           diterapkan SAAT SKOR DIBACA (`apply_seasonality`) pada skor dasar, dibatasi
           10, lalu `risk_level` ditentukan dari skor AKHIR itu. Jadi pergantian musim
           langsung berlaku tanpa menghitung ulang; tanggal yang dipakai = tanggal
           pertanyaan ("sekarang" bila tidak ditentukan; tanggal berangkat pada rute).
- Sumber : seed data (`is_seed_data`) + insiden komunitas berstatus
           'terverifikasi' saja (REQ-F-022). Insiden 'baru' (belum ada
           korroborasi) TIDAK ikut dihitung.

Kalibrasi skala (`risk_score_saturation_scale` = 3.0, ASUMSI SIMULASI). Skor dasar
untuk n insiden berbobot ~1 di satu sel dan bucket (ambang: sedang >= 3, tinggi >= 7):

    n insiden |   1    |   2    |   3    |   4    |   6
    skor      |  2.83  |  4.87  |  6.32  |  7.36  |  8.65
    level     | rendah | sedang | sedang | tinggi | tinggi

Satu insiden saja tidak langsung sedang/tinggi; dua insiden sekitar waktu yang sama
sudah sedang; empat sudah tinggi. Seed data lama berbobot < 1 (mis. kejadian 4,5
tahun lalu ~0.54 -> skor 1.65), jadi butuh lebih banyak insiden untuk naik level.
Pengali musim saat membaca: 1 insiden (2.83) x 1.3 jelang Ramadan = 3.68 -> sedang.

KNOWN LIMITATIONS:
- Skor dasar mencerminkan WAKTU HITUNG TERAKHIR (bobot umur kejadian). Diperbarui
  otomatis tiap ada insiden yang terverifikasi (fig4 SRS langkah 5-6); pengali musim
  TIDAK lagi butuh penjadwalan ulang. Bobot umur tetap bergeser pelan seiring waktu,
  jadi hitung ulang berkala (`python -m app.scripts.recalculate_risk`) masih disarankan.
- Sel tanpa insiden tidak punya baris (`has_data=False` di lookup), bukan
  berarti "aman" — hanya "belum ada data".
- Label area berupa koordinat grid, belum nama wilayah resmi.
"""

import logging
import math
import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from hijri_converter import Gregorian, Hijri
from supabase import Client

from app.core.areas import AreaDirectory, AreasUnavailable, get_area_directory
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.core.timeutil import WIB, to_wib  # noqa: F401 - WIB/to_wib tetap diekspor dari modul ini

logger = logging.getLogger(__name__)

DINI_HARI = "dini_hari"
JELANG_RAMADAN = "jelang_ramadan"
SELAMA_RAMADAN = "selama_ramadan"
# (bucket, jam mulai, jam selesai-eksklusif) dalam jam WIB; harus menutup 0-24.
TIME_BUCKET_HOURS = (
    (DINI_HARI, 0, 5),
    ("pagi", 5, 11),
    ("siang", 11, 15),
    ("sore", 15, 18),
    ("malam", 18, 24),
)

_PAGE_SIZE = 1000
_UPSERT_CHUNK_SIZE = 500
_MAX_SCORE = 10.0


@dataclass(frozen=True)
class ScorableIncident:
    """Insiden yang ikut dihitung: cuma posisi & waktu, tanpa teks apa pun."""

    latitude: float
    longitude: float
    incident_time: datetime  # timezone-aware


@dataclass(frozen=True)
class RiskScoreRow:
    area_name: str
    latitude: float  # pusat sel grid, BUKAN koordinat insiden asli
    longitude: float
    time_bucket: str
    risk_score: float
    risk_level: str
    contributing_incident_count: int
    place_name: str | None = None  # "Kec. X" (kecamatan terdekat), diisi assign_places saat hitung ulang
    kecamatan_kode: str | None = None


@dataclass(frozen=True)
class RiskLookup:
    """Skor yang dibaca. `risk_score`/`risk_level` = skor AKHIR (skor dasar tersimpan x pengali
    musim pada tanggal pertanyaan, dibatasi 10); `base_score` = skor dasar tersimpan."""

    area_name: str
    time_bucket: str
    risk_score: float
    risk_level: str
    contributing_incident_count: int
    has_data: bool
    # Kapan skor dasar tersimpan ini dihitung (konteks tambahan saja).
    last_calculated_at: datetime | None = None
    base_score: float = 0.0
    season: str | None = None  # JELANG_RAMADAN / SELAMA_RAMADAN / None — musim pada tanggal pertanyaan
    season_multiplier: float = 1.0  # pengali yang BENAR-BENAR diterapkan ke base_score
    place_name: str | None = None  # label publik wilayah ("Kec. X"); None -> tampilkan area_name


@dataclass(frozen=True)
class RiskCell:
    """Satu sel skor untuk dasbor peta. Koordinat = pusat sel grid publik.
    `risk_score`/`risk_level` = skor AKHIR (sudah dikali pengali musim)."""

    area_name: str
    latitude: float
    longitude: float
    time_bucket: str
    risk_score: float
    risk_level: str
    contributing_incident_count: int
    last_calculated_at: datetime | None
    base_score: float = 0.0
    season: str | None = None
    season_multiplier: float = 1.0
    place_name: str | None = None
    kecamatan_kode: str | None = None


@dataclass(frozen=True)
class RegionSummary:
    """Ringkasan skor satu kecamatan untuk satu bucket jam (agregat dari sel-selnya)."""

    kecamatan_kode: str
    place_name: str
    risk_score: float  # skor AKHIR tertinggi di antara sel-selnya
    risk_level: str  # level dari skor akhir tertinggi itu (sudah termasuk pengali musim)
    cell_count: int
    incident_count: int  # jumlah kontribusi insiden pada sel-sel kecamatan itu


@dataclass(frozen=True)
class RecalculationResult:
    rows: list[RiskScoreRow] = field(default_factory=list)
    incidents_used: int = 0
    incidents_skipped_without_coordinates: int = 0
    upserted: int = 0
    deleted: int = 0
    # True = hasil perhitungan KOSONG dan penyimpanan dibatalkan (skor lama dipertahankan);
    # lihat parameter `allow_empty` di recalculate_risk_scores.
    blocked_empty: bool = False
    # True = nama wilayah (place_name) ikut diperbarui; False = direktori wilayah tak terbaca/kosong,
    # kolom nama di database sengaja TIDAK disentuh (label lama dipertahankan).
    names_resolved: bool = False


# ---------------------------------------------------------------- fungsi murni


def time_bucket_of(moment: datetime) -> str:
    """Bucket rentang waktu (jam WIB) untuk sebuah momen."""
    hour = to_wib(moment).hour
    for bucket, start_hour, end_hour in TIME_BUCKET_HOURS:
        if start_hour <= hour < end_hour:
            return bucket
    raise ValueError(f"Jam di luar 0-23: {hour}")  # tidak terjangkau; jaga-jaga


def cell_index(latitude: float, longitude: float, cell_degrees: float) -> tuple[int, int]:
    """Indeks (baris, kolom) sel grid yang memuat sebuah koordinat."""
    return math.floor(latitude / cell_degrees), math.floor(longitude / cell_degrees)


def area_from_index(row: int, col: int, cell_degrees: float) -> tuple[float, float, str]:
    """(lat pusat, lon pusat, label area netral) untuk sel (baris, kolom)."""
    center_lat = round((row + 0.5) * cell_degrees, 6)
    center_lon = round((col + 0.5) * cell_degrees, 6)
    return center_lat, center_lon, f"Area {center_lat:.3f}, {center_lon:.3f}"


def locate_area(latitude: float, longitude: float, cell_degrees: float) -> tuple[float, float, str]:
    """Petakan koordinat ke sel grid: (lat pusat, lon pusat, label area netral).

    Satu-satunya tempat label area dibuat, dipakai perhitungan MAUPUN lookup,
    supaya keduanya pasti menghasilkan kunci yang sama untuk sel yang sama.
    """
    return area_from_index(*cell_index(latitude, longitude, cell_degrees), cell_degrees)


def recency_weight(incident_time: datetime, as_of: datetime, half_life_days: int) -> float:
    """Bobot 0-1: 1.0 untuk kejadian terbaru, separuh setiap `half_life_days`."""
    age_days = max(0.0, (as_of - incident_time).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life_days)


@lru_cache(maxsize=None)
def _ramadan_window(hijri_year: int) -> tuple[date, date]:
    """(tanggal 1 Ramadan, hari setelah Ramadan berakhir) untuk tahun Hijriah."""
    first_day = Hijri(hijri_year, 9, 1)
    start = first_day.to_gregorian()
    start_date = date(start.year, start.month, start.day)
    return start_date, start_date + timedelta(days=first_day.month_length())


def ramadan_phase(on_date: date, settings: Settings) -> str | None:
    """Fase musim pada tanggal itu: JELANG_RAMADAN, SELAMA_RAMADAN, atau None.

    Satu-satunya tempat jendela Ramadan dihitung — dipakai pengali skor MAUPUN
    narasi, supaya penjelasan tidak pernah menyebut musim yang berbeda dari
    yang benar-benar dipakai rumus. Tanggal di luar jangkauan konversi Hijriah
    (sebelum 1924 / sesudah 2077) -> None dengan peringatan, bukan error.
    """
    try:
        hijri_year = Gregorian(on_date.year, on_date.month, on_date.day).to_hijri().year
        windows = [_ramadan_window(year) for year in (hijri_year - 1, hijri_year, hijri_year + 1)]
    except (OverflowError, ValueError):
        logger.warning("Tanggal %s di luar jangkauan konversi Hijriah, pola musiman dilewati", on_date)
        return None

    lead = timedelta(days=settings.risk_ramadan_lead_days)
    for start, end in windows:
        if start - lead <= on_date < start:
            return JELANG_RAMADAN
        if start <= on_date < end:
            return SELAMA_RAMADAN
    return None


def seasonal_multiplier(on_date: date, time_bucket: str, settings: Settings) -> float:
    """Pengali musiman (REQ-F-023): >1 jelang & selama Ramadan, 1.0 di luar itu.

    Selama Ramadan bucket dini_hari (jam sahur, SOTR menurut catatan JPW di SRS)
    mendapat pengali tambahan.
    """
    phase = ramadan_phase(on_date, settings)
    if phase == JELANG_RAMADAN:
        return settings.risk_ramadan_multiplier
    if phase == SELAMA_RAMADAN:
        multiplier = settings.risk_ramadan_multiplier
        if time_bucket == DINI_HARI:
            multiplier *= settings.risk_ramadan_dini_hari_multiplier
        return multiplier
    return 1.0


def risk_level_for(score: float, settings: Settings) -> str:
    """Terjemahan skor ke tingkat — nilai harus sama dengan CHECK constraint di DB."""
    if score >= settings.risk_level_high_threshold:
        return "tinggi"
    if score >= settings.risk_level_medium_threshold:
        return "sedang"
    return "rendah"


_NEIGHBOR_OFFSETS = tuple((dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0))


def base_score_from_intensity(intensity: float, settings: Settings) -> float:
    """Skor DASAR 0-10 (tanpa pengali musim) dari intensitas — jenuh mulus menuju 10."""
    return round(min(_MAX_SCORE, _MAX_SCORE * (1 - math.exp(-intensity / settings.risk_score_saturation_scale))), 2)


@dataclass(frozen=True)
class SeasonalScore:
    """Skor AKHIR setelah pengali musim diterapkan saat baca."""

    score: float
    level: str
    multiplier: float
    phase: str | None  # JELANG_RAMADAN / SELAMA_RAMADAN / None


def apply_seasonality(base_score: float, on_date: date, time_bucket: str, settings: Settings) -> SeasonalScore:
    """Skor akhir = skor dasar x pengali musim pada `on_date`, dibatasi 10; `risk_level`
    ditentukan dari skor akhir (bukan dari level dasar yang tersimpan)."""
    multiplier = seasonal_multiplier(on_date, time_bucket, settings)
    score = round(min(_MAX_SCORE, base_score * multiplier), 2)
    return SeasonalScore(
        score=score,
        level=risk_level_for(score, settings),
        multiplier=multiplier,
        phase=ramadan_phase(on_date, settings),
    )


def today_wib() -> date:
    """Tanggal hari ini (WIB) — satu titik supaya mudah dipin di test."""
    return datetime.now(WIB).date()


def compute_risk_scores(
    incidents: Iterable[ScorableIncident], as_of: datetime, settings: Settings
) -> list[RiskScoreRow]:
    """Hitung skor DASAR per (sel area, bucket waktu) — fungsi murni, tanpa I/O.

    Pengali musim TIDAK diterapkan di sini (lihat `apply_seasonality`, dipakai saat baca).
    Insiden juga menyumbang `risk_neighbor_weight` x bobotnya ke 8 sel tetangga."""
    as_of_wib = to_wib(as_of)
    own_weights: dict[tuple[int, int, str], list[float]] = defaultdict(list)

    for incident in incidents:
        row, col = cell_index(incident.latitude, incident.longitude, settings.risk_grid_cell_degrees)
        bucket = time_bucket_of(incident.incident_time)
        own_weights[(row, col, bucket)].append(
            recency_weight(incident.incident_time, as_of_wib, settings.risk_recency_half_life_days)
        )

    intensity: dict[tuple[int, int, str], float] = defaultdict(float)
    for key, weights in own_weights.items():
        intensity[key] += sum(weights)
    if settings.risk_neighbor_weight > 0:
        for (row, col, bucket), weights in own_weights.items():
            spill = settings.risk_neighbor_weight * sum(weights)
            for d_row, d_col in _NEIGHBOR_OFFSETS:
                intensity[(row + d_row, col + d_col, bucket)] += spill

    rows: list[RiskScoreRow] = []
    for (row, col, bucket), total in intensity.items():
        score = base_score_from_intensity(total, settings)
        if score <= 0:
            continue
        own = own_weights.get((row, col, bucket))
        if own is None and score < settings.risk_neighbor_min_score:
            continue  # sel tetangga tanpa insiden sendiri & skor terlalu kecil: tidak diberi baris
        center_lat, center_lon, area_name = area_from_index(row, col, settings.risk_grid_cell_degrees)
        rows.append(
            RiskScoreRow(
                area_name=area_name,
                latitude=center_lat,
                longitude=center_lon,
                time_bucket=bucket,
                risk_score=score,
                risk_level=risk_level_for(score, settings),
                contributing_incident_count=len(own) if own else 0,
            )
        )
    return sorted(rows, key=lambda r: (r.area_name, r.time_bucket))


def public_label(place_name: str | None, area_name: str) -> str:
    """Label publik sebuah sel: nama wilayah nyata bila ada, selain itu label grid netral."""
    return place_name or area_name


def assign_places(rows: list[RiskScoreRow], directory: AreaDirectory, settings: Settings) -> list[RiskScoreRow]:
    """Beri tiap baris skor nama kecamatan TERDEKAT dari pusat sel grid (fungsi murni, tanpa jaringan).

    Sel yang tak punya kecamatan dalam `risk_place_max_distance_meters` dibiarkan tanpa nama
    (`place_name=None`) dan tetap tampil dengan label grid netral. Ini pendekatan "pusat terdekat",
    bukan batas poligon resmi: sel di perbatasan bisa mendapat kecamatan tetangga yang pusatnya
    lebih dekat."""
    named: list[RiskScoreRow] = []
    for row in rows:
        kecamatan = directory.nearest_kecamatan(row.latitude, row.longitude, settings.risk_place_max_distance_meters)
        if kecamatan is None:
            named.append(replace(row, place_name=None, kecamatan_kode=None))
        else:
            named.append(replace(row, place_name=directory.place_name(kecamatan), kecamatan_kode=kecamatan.kode))
    return named


def summarize_by_kecamatan(cells: list[RiskCell]) -> tuple[list[RegionSummary], int]:
    """Agregasi sel per kecamatan (fungsi murni): skor tertinggi, jumlah sel, total insiden kontribusi.

    Urut skor tertinggi (lalu insiden terbanyak, lalu nama) supaya deterministik. Sel tanpa
    `kecamatan_kode` (tak ada kecamatan dekat / belum dihitung ulang) tidak masuk ringkasan dan
    dihitung terpisah (elemen kedua). Level diambil dari sel berskor tertinggi: level selalu turunan
    dari skor akhir, jadi tidak ada ketidakcocokan dengan pengali musim."""
    grouped: dict[str, list[RiskCell]] = {}
    unassigned = 0
    for cell in cells:
        if cell.kecamatan_kode is None:
            unassigned += 1
        else:
            grouped.setdefault(cell.kecamatan_kode, []).append(cell)

    regions: list[RegionSummary] = []
    for kode, group in grouped.items():
        top = max(group, key=lambda c: c.risk_score)
        regions.append(
            RegionSummary(
                kecamatan_kode=kode,
                place_name=next((c.place_name for c in group if c.place_name), kode),
                risk_score=top.risk_score,
                risk_level=top.risk_level,
                cell_count=len(group),
                incident_count=sum(c.contributing_incident_count for c in group),
            )
        )
    regions.sort(key=lambda r: (-r.risk_score, -r.incident_count, r.place_name))
    return regions, unassigned


def _resolve_directory(supabase: Client) -> AreaDirectory | None:
    """Direktori wilayah untuk penamaan, atau None bila tak terbaca/kosong (hitung ulang skor tetap jalan)."""
    try:
        directory = get_area_directory(supabase)
    except AreasUnavailable:
        logger.warning("Data wilayah tak terbaca: skor dihitung ulang TANPA memperbarui nama wilayah")
        return None
    if len(directory) == 0:
        logger.warning("Tabel areas kosong (jalankan app.scripts.load_areas): nama wilayah tidak diperbarui")
        return None
    return directory


# ------------------------------------------------------------- akses database


def _fetch_scorable_incidents(supabase: Client) -> tuple[list[ScorableIncident], int]:
    """Ambil seed data + insiden komunitas terverifikasi (REQ-F-022).

    Return (insiden ber-koordinat, jumlah yang dilewati karena tanpa koordinat).
    """
    incidents: list[ScorableIncident] = []
    skipped = 0
    start = 0
    while True:
        response = execute_with_retry(
            supabase.table("incidents")
            .select("latitude,longitude,incident_time")
            .or_("is_seed_data.eq.true,status.eq.terverifikasi")
            .order("id")
            .range(start, start + _PAGE_SIZE - 1)
        )
        rows = response.data or []
        for row in rows:
            if row.get("latitude") is None or row.get("longitude") is None:
                skipped += 1
                continue
            incidents.append(
                ScorableIncident(
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    incident_time=to_wib(datetime.fromisoformat(row["incident_time"])),
                )
            )
        if len(rows) < _PAGE_SIZE:
            return incidents, skipped
        start += _PAGE_SIZE


def _fetch_existing_score_keys(supabase: Client) -> list[dict]:
    keys: list[dict] = []
    start = 0
    while True:
        response = execute_with_retry(
            supabase.table("risk_scores")
            .select("id,area_name,time_bucket")
            .order("id")
            .range(start, start + _PAGE_SIZE - 1)
        )
        rows = response.data or []
        keys.extend(rows)
        if len(rows) < _PAGE_SIZE:
            return keys
        start += _PAGE_SIZE


def _persist_scores(
    supabase: Client, rows: list[RiskScoreRow], calculated_at: datetime, *, include_names: bool = False
) -> tuple[int, int]:
    """Upsert skor baru lalu hapus baris usang. Return (jumlah upsert, jumlah dihapus).

    Upsert DULU baru hapus, supaya pembaca publik tidak pernah melihat tabel
    kosong di tengah perhitungan ulang.
    """
    existing = _fetch_existing_score_keys(supabase)
    payload = [
        {
            "area_name": row.area_name,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "time_bucket": row.time_bucket,
            "risk_score": row.risk_score,
            "risk_level": row.risk_level,
            "contributing_incident_count": row.contributing_incident_count,
            "last_calculated_at": calculated_at.isoformat(),
            # Nama hanya ditulis bila direktori wilayah berhasil dibaca; kalau tidak, label lama dibiarkan.
            **({"place_name": row.place_name, "kecamatan_kode": row.kecamatan_kode} if include_names else {}),
        }
        for row in rows
    ]
    for chunk_start in range(0, len(payload), _UPSERT_CHUNK_SIZE):
        execute_with_retry(
            supabase.table("risk_scores").upsert(
                payload[chunk_start : chunk_start + _UPSERT_CHUNK_SIZE],
                on_conflict="area_name,time_bucket",
            )
        )

    keep = {(row.area_name, row.time_bucket) for row in rows}
    stale_ids = [key["id"] for key in existing if (key["area_name"], key["time_bucket"]) not in keep]
    if stale_ids:
        execute_with_retry(supabase.table("risk_scores").delete().in_("id", stale_ids))
    return len(payload), len(stale_ids)


def _count_all_incidents(supabase: Client) -> int | None:
    """Jumlah SEMUA baris `incidents` (hanya untuk pesan peringatan; None kalau gagal dihitung)."""
    try:
        return execute_with_retry(supabase.table("incidents").select("id", count="exact").limit(1)).count
    except Exception as exc:  # noqa: BLE001 - hanya pelengkap pesan; keputusan pengaman tidak bergantung padanya
        logger.warning("Jumlah baris incidents tidak terbaca: %s", safe_error_summary(exc))
        return None


def recalculate_risk_scores(
    as_of: datetime | None = None,
    *,
    supabase: Client | None = None,
    persist: bool = True,
    allow_empty: bool = False,
) -> RecalculationResult:
    """Hitung ulang SEMUA skor dasar kerawanan dari data saat ini (REQ-F-020/022).

    `as_of` (default: sekarang) menentukan bobot umur kejadian (pengali musim tidak
    termasuk — diterapkan saat baca). `persist=False` = dry run: hanya menghitung,
    tidak menyentuh tabel `risk_scores`. Exception dari database dilempar ke pemanggil
    (CLI); jalur otomatis pakai refresh_risk_scores_safely() yang menelannya.

    PENGAMAN HASIL KOSONG: kalau perhitungan menghasilkan NOL baris, penyimpanan
    DIBATALKAN dan skor lama dipertahankan (`blocked_empty=True`) — kecuali
    `allow_empty=True`. Tanpa ini, satu bacaan yang keliru (insiden belum terbaca,
    semua insiden tanpa koordinat, tabel sementara kosong) akan menghapus seluruh
    peta kerawanan publik. Kegagalan membaca database sudah melempar exception
    SEBELUM tahap simpan, jadi tidak pernah sampai ke penghapusan.
    """
    settings = get_settings()
    moment = as_of or datetime.now(WIB)
    client = supabase or get_supabase()

    incidents, skipped = _fetch_scorable_incidents(client)
    rows = compute_risk_scores(incidents, moment, settings)
    directory = _resolve_directory(client)
    if directory is not None:
        rows = assign_places(rows, directory, settings)

    if persist and not rows and not allow_empty:
        total = _count_all_incidents(client)
        if total:
            logger.warning(
                "Hasil perhitungan skor KOSONG padahal tabel incidents berisi %d baris "
                "(%d dinilai, %d tanpa koordinat): skor lama DIPERTAHANKAN, tidak ada yang dihapus.",
                total,
                len(incidents),
                skipped,
            )
        else:
            logger.warning(
                "Hasil perhitungan skor KOSONG dan tidak ada insiden sama sekali: skor lama DIPERTAHANKAN. "
                "Untuk benar-benar mengosongkan risk_scores jalankan dengan allow_empty / --allow-empty."
            )
        return RecalculationResult(
            rows=[],
            incidents_used=len(incidents),
            incidents_skipped_without_coordinates=skipped,
            blocked_empty=True,
        )

    upserted = deleted = 0
    if persist:
        upserted, deleted = _persist_scores(
            client, rows, calculated_at=datetime.now(timezone.utc), include_names=directory is not None
        )
        _notify_recalculated()
    return RecalculationResult(
        rows=rows,
        incidents_used=len(incidents),
        incidents_skipped_without_coordinates=skipped,
        upserted=upserted,
        deleted=deleted,
        names_resolved=directory is not None,
    )


# -------------------------------------------------- pemicu otomatis (fig4 SRS)

_recalculation_listeners: list = []


def add_recalculation_listener(listener) -> None:
    """Daftarkan fungsi tanpa argumen yang dipanggil SETELAH skor berhasil dihitung ulang & disimpan
    (mis. membuang cache turunan data insiden). Kegagalan listener tidak mengganggu perhitungan."""
    if listener not in _recalculation_listeners:
        _recalculation_listeners.append(listener)


def _notify_recalculated() -> None:
    for listener in _recalculation_listeners:
        try:
            listener()
        except Exception as exc:  # noqa: BLE001 - listener tidak boleh menggagalkan perhitungan skor
            logger.error("Listener pasca-hitung-ulang gagal: %s", safe_error_summary(exc))


_state_lock = threading.Lock()
_recalculation_running = False
_rerun_requested = False


def refresh_risk_scores_safely() -> None:
    """Dipanggil Verification Agent begitu sebuah insiden terverifikasi
    (diagram sekuens SRS fig4 langkah 5-6). TIDAK PERNAH melempar exception:
    kegagalan cuma dicatat (aman, tanpa data laporan), skor lama tetap dipakai
    sampai pemicu berikutnya.

    Coalescing: kalau perhitungan sedang berjalan (mis. 20 laporan terverifikasi
    hampir bersamaan), pemicu baru tidak memulai perhitungan paralel — cukup
    menandai "ulangi sekali lagi setelah selesai". Perhitungan itu idempoten
    (upsert penuh + hapus baris usang), jadi satu putaran ulang sudah mencakup
    semua pemicu yang datang di tengah jalan.
    """
    global _recalculation_running, _rerun_requested
    with _state_lock:
        if _recalculation_running:
            _rerun_requested = True
            return
        _recalculation_running = True

    try:
        while True:
            with _state_lock:
                _rerun_requested = False
            try:
                result = recalculate_risk_scores()
                logger.info(
                    "Skor kerawanan dihitung ulang: %d insiden -> %d baris (%d dihapus)",
                    result.incidents_used,
                    result.upserted,
                    result.deleted,
                )
            except Exception as exc:  # noqa: BLE001 - kegagalan skor tidak boleh mengganggu verifikasi
                logger.error("Perhitungan ulang skor kerawanan GAGAL: %s", safe_error_summary(exc))
            with _state_lock:
                if not _rerun_requested:
                    _recalculation_running = False
                    return
    except BaseException:
        with _state_lock:
            _recalculation_running = False
        raise


# ------------------------------------------------------------- pembacaan skor


def lookup_risk_score(
    supabase: Client, latitude: float, longitude: float, at: datetime
) -> RiskLookup:
    """Skor untuk sel yang memuat koordinat, di bucket waktu `at`.

    Dipakai TC-RSK-001. Tanpa baris -> skor 0.0, level 'rendah', has_data=False
    (belum ada data, BUKAN jaminan aman). `at` memilih bucket jam DAN tanggal untuk
    pengali musim: skor dasar tersimpan dikali pengali Ramadan pada tanggal itu
    (dibatasi 10) dan `risk_level` ditentukan dari skor akhir.
    """
    settings = get_settings()
    _, _, area_name = locate_area(latitude, longitude, settings.risk_grid_cell_degrees)
    bucket = time_bucket_of(at)
    response = execute_with_retry(
        supabase.table("risk_scores")
        .select("risk_score,risk_level,contributing_incident_count,last_calculated_at,place_name")
        .eq("area_name", area_name)
        .eq("time_bucket", bucket)
        .limit(1)
    )
    if not response.data:
        return RiskLookup(area_name, bucket, 0.0, "rendah", 0, has_data=False)
    row = response.data[0]
    base_score = float(row["risk_score"])
    seasonal = apply_seasonality(base_score, to_wib(at).date(), bucket, settings)
    return RiskLookup(
        area_name=area_name,
        time_bucket=bucket,
        risk_score=seasonal.score,
        risk_level=seasonal.level,
        contributing_incident_count=int(row["contributing_incident_count"]),
        has_data=True,
        last_calculated_at=_parse_timestamp(row.get("last_calculated_at")),
        base_score=base_score,
        season=seasonal.phase,
        season_multiplier=seasonal.multiplier,
        place_name=row.get("place_name"),
    )


def _parse_timestamp(raw: object) -> datetime | None:
    """ISO timestamp dari PostgREST -> datetime; nilai kosong/rusak -> None
    (hanya konteks tambahan untuk narasi, tidak boleh menggagalkan lookup skor)."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("Format last_calculated_at tidak dikenali, konteks musim narasi dilewati")
        return None


def fetch_risk_cells(supabase: Client, time_bucket: str, on_date: date | None = None) -> list[RiskCell]:
    """Semua sel skor untuk satu bucket jam (bahan heatmap, REQ-F-040).

    Hanya baca `risk_scores` (RLS: baca publik). Skor dasar tersimpan dikali pengali musim
    pada `on_date` (default: hari ini WIB), dibatasi 10; level dari skor akhir. Dipaginasi
    supaya tidak terpotong batas baris PostgREST; baris tanpa koordinat dilewati. Error
    database dibiarkan naik ke pemanggil (API yang memetakannya ke 502).
    """
    settings = get_settings()
    on_date = on_date or today_wib()
    cells: list[RiskCell] = []
    start = 0
    while True:
        response = execute_with_retry(
            supabase.table("risk_scores")
            .select(
                "area_name,latitude,longitude,time_bucket,risk_score,risk_level,"
                "contributing_incident_count,last_calculated_at,place_name,kecamatan_kode"
            )
            .eq("time_bucket", time_bucket)
            .order("area_name")
            .range(start, start + _PAGE_SIZE - 1)
        )
        rows = response.data or []
        for row in rows:
            if row.get("latitude") is None or row.get("longitude") is None:
                continue
            base_score = float(row["risk_score"])
            seasonal = apply_seasonality(base_score, on_date, row["time_bucket"], settings)
            cells.append(
                RiskCell(
                    area_name=row["area_name"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    time_bucket=row["time_bucket"],
                    risk_score=seasonal.score,
                    risk_level=seasonal.level,
                    contributing_incident_count=int(row["contributing_incident_count"]),
                    last_calculated_at=_parse_timestamp(row.get("last_calculated_at")),
                    base_score=base_score,
                    season=seasonal.phase,
                    season_multiplier=seasonal.multiplier,
                    place_name=row.get("place_name"),
                    kecamatan_kode=row.get("kecamatan_kode"),
                )
            )
        if len(rows) < _PAGE_SIZE:
            return cells
        start += _PAGE_SIZE
