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
- Waktu  : 5 bucket jam WIB (dini_hari, pagi, siang, sore, malam).
- Bobot  : tiap insiden berbobot 0.5 ** (umur / half-life) — kejadian lama
           tetap dihitung tapi makin kecil pengaruhnya (half-life panjang supaya
           seed data historis 2020-2023 masih berpengaruh, REQ-F-021 cold start).
- Musim  : intensitas dikali pengali saat jelang/selama Ramadan, dan tambahan di
           jam sahur (dini_hari) selama Ramadan karena SOTR (REQ-F-023).
- Skor   : 10 * (1 - exp(-intensitas / skala)) — jenuh mulus di bawah 10, tanpa
           perlu normalisasi global (satu titik panas tidak menekan area lain).
- Sumber : seed data (`is_seed_data`) + insiden komunitas berstatus
           'terverifikasi' saja (REQ-F-022). Insiden 'baru' (belum ada
           korroborasi) TIDAK ikut dihitung.

KNOWN LIMITATIONS:
- Skor tersimpan mencerminkan WAKTU HITUNG TERAKHIR (termasuk pengali musim).
  Diperbarui otomatis tiap ada insiden yang terverifikasi (fig4 SRS langkah
  5-6); pergantian musim tanpa laporan baru butuh penjadwalan CLI
  `python -m app.scripts.recalculate_risk` (cron/scheduler platform).
- Sel tanpa insiden tidak punya baris (`has_data=False` di lookup), bukan
  berarti "aman" — hanya "belum ada data".
- Label area berupa koordinat grid, belum nama wilayah resmi.
"""

import logging
import math
import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from hijri_converter import Gregorian, Hijri
from supabase import Client

from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

# Yogyakarta = WIB (UTC+7), tanpa DST — offset tetap cukup dan tidak butuh
# database zona waktu (zoneinfo di Windows butuh paket tzdata tambahan).
WIB = timezone(timedelta(hours=7))

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


@dataclass(frozen=True)
class RiskLookup:
    area_name: str
    time_bucket: str
    risk_score: float
    risk_level: str
    contributing_incident_count: int
    has_data: bool
    # Kapan skor tersimpan ini dihitung; menentukan musim yang tertanam di angkanya.
    last_calculated_at: datetime | None = None


@dataclass(frozen=True)
class RiskCell:
    """Satu sel skor tersimpan untuk dasbor peta. Koordinat = pusat sel grid publik."""

    area_name: str
    latitude: float
    longitude: float
    time_bucket: str
    risk_score: float
    risk_level: str
    contributing_incident_count: int
    last_calculated_at: datetime | None


@dataclass(frozen=True)
class RecalculationResult:
    rows: list[RiskScoreRow] = field(default_factory=list)
    incidents_used: int = 0
    incidents_skipped_without_coordinates: int = 0
    upserted: int = 0
    deleted: int = 0


# ---------------------------------------------------------------- fungsi murni


def to_wib(moment: datetime) -> datetime:
    """Kalau `moment` naive dianggap sudah WIB (waktu lokal pengguna)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=WIB)
    return moment.astimezone(WIB)


def time_bucket_of(moment: datetime) -> str:
    """Bucket rentang waktu (jam WIB) untuk sebuah momen."""
    hour = to_wib(moment).hour
    for bucket, start_hour, end_hour in TIME_BUCKET_HOURS:
        if start_hour <= hour < end_hour:
            return bucket
    raise ValueError(f"Jam di luar 0-23: {hour}")  # tidak terjangkau; jaga-jaga


def locate_area(latitude: float, longitude: float, cell_degrees: float) -> tuple[float, float, str]:
    """Petakan koordinat ke sel grid: (lat pusat, lon pusat, label area netral).

    Satu-satunya tempat label area dibuat, dipakai perhitungan MAUPUN lookup,
    supaya keduanya pasti menghasilkan kunci yang sama untuk sel yang sama.
    """
    row = math.floor(latitude / cell_degrees)
    col = math.floor(longitude / cell_degrees)
    center_lat = round((row + 0.5) * cell_degrees, 6)
    center_lon = round((col + 0.5) * cell_degrees, 6)
    return center_lat, center_lon, f"Area {center_lat:.3f}, {center_lon:.3f}"


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


def compute_risk_scores(
    incidents: Iterable[ScorableIncident], as_of: datetime, settings: Settings
) -> list[RiskScoreRow]:
    """Hitung skor per (sel area, bucket waktu) — fungsi murni, tanpa I/O."""
    as_of_wib = to_wib(as_of)
    weights: dict[tuple[str, str], list[float]] = defaultdict(list)
    centers: dict[str, tuple[float, float]] = {}

    for incident in incidents:
        center_lat, center_lon, area_name = locate_area(
            incident.latitude, incident.longitude, settings.risk_grid_cell_degrees
        )
        centers[area_name] = (center_lat, center_lon)
        bucket = time_bucket_of(incident.incident_time)
        weights[(area_name, bucket)].append(
            recency_weight(incident.incident_time, as_of_wib, settings.risk_recency_half_life_days)
        )

    rows: list[RiskScoreRow] = []
    for (area_name, bucket), cell_weights in weights.items():
        intensity = sum(cell_weights) * seasonal_multiplier(as_of_wib.date(), bucket, settings)
        score = round(
            min(_MAX_SCORE, _MAX_SCORE * (1 - math.exp(-intensity / settings.risk_score_saturation_scale))),
            2,
        )
        if score <= 0:
            continue
        center_lat, center_lon = centers[area_name]
        rows.append(
            RiskScoreRow(
                area_name=area_name,
                latitude=center_lat,
                longitude=center_lon,
                time_bucket=bucket,
                risk_score=score,
                risk_level=risk_level_for(score, settings),
                contributing_incident_count=len(cell_weights),
            )
        )
    return sorted(rows, key=lambda row: (row.area_name, row.time_bucket))


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
    supabase: Client, rows: list[RiskScoreRow], calculated_at: datetime
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


def recalculate_risk_scores(
    as_of: datetime | None = None,
    *,
    supabase: Client | None = None,
    persist: bool = True,
) -> RecalculationResult:
    """Hitung ulang SEMUA skor kerawanan dari data saat ini (REQ-F-020/022/023).

    `as_of` (default: sekarang) menentukan bobot kejadian & pengali musiman.
    `persist=False` = dry run: hanya menghitung, tidak menyentuh tabel
    `risk_scores`. Exception dari database dilempar ke pemanggil (CLI); jalur
    otomatis pakai refresh_risk_scores_safely() yang menelannya.
    """
    settings = get_settings()
    moment = as_of or datetime.now(WIB)
    client = supabase or get_supabase()

    incidents, skipped = _fetch_scorable_incidents(client)
    rows = compute_risk_scores(incidents, moment, settings)

    upserted = deleted = 0
    if persist:
        upserted, deleted = _persist_scores(client, rows, calculated_at=datetime.now(timezone.utc))
    return RecalculationResult(
        rows=rows,
        incidents_used=len(incidents),
        incidents_skipped_without_coordinates=skipped,
        upserted=upserted,
        deleted=deleted,
    )


# -------------------------------------------------- pemicu otomatis (fig4 SRS)

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
    """Skor tersimpan untuk sel yang memuat koordinat, di bucket waktu `at`.

    Dipakai TC-RSK-001 dan nanti Safe Route Advisor. Tanpa baris -> skor 0.0,
    level 'rendah', has_data=False (belum ada data, BUKAN jaminan aman).
    `at` hanya memilih bucket jam; pengali musim sudah tertanam di skor
    tersimpan pada waktu hitung terakhir.
    """
    settings = get_settings()
    _, _, area_name = locate_area(latitude, longitude, settings.risk_grid_cell_degrees)
    bucket = time_bucket_of(at)
    response = execute_with_retry(
        supabase.table("risk_scores")
        .select("risk_score,risk_level,contributing_incident_count,last_calculated_at")
        .eq("area_name", area_name)
        .eq("time_bucket", bucket)
        .limit(1)
    )
    if not response.data:
        return RiskLookup(area_name, bucket, 0.0, "rendah", 0, has_data=False)
    row = response.data[0]
    return RiskLookup(
        area_name=area_name,
        time_bucket=bucket,
        risk_score=float(row["risk_score"]),
        risk_level=row["risk_level"],
        contributing_incident_count=int(row["contributing_incident_count"]),
        has_data=True,
        last_calculated_at=_parse_timestamp(row.get("last_calculated_at")),
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


def fetch_risk_cells(supabase: Client, time_bucket: str) -> list[RiskCell]:
    """Semua sel skor tersimpan untuk satu bucket jam (bahan heatmap, REQ-F-040).

    Hanya baca `risk_scores` (RLS: baca publik). Dipaginasi supaya tidak terpotong
    batas baris PostgREST; baris tanpa koordinat dilewati. Error database dibiarkan
    naik ke pemanggil (API yang memetakannya ke 502).
    """
    cells: list[RiskCell] = []
    start = 0
    while True:
        response = execute_with_retry(
            supabase.table("risk_scores")
            .select(
                "area_name,latitude,longitude,time_bucket,risk_score,risk_level,"
                "contributing_incident_count,last_calculated_at"
            )
            .eq("time_bucket", time_bucket)
            .order("area_name")
            .range(start, start + _PAGE_SIZE - 1)
        )
        rows = response.data or []
        for row in rows:
            if row.get("latitude") is None or row.get("longitude") is None:
                continue
            cells.append(
                RiskCell(
                    area_name=row["area_name"],
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    time_bucket=row["time_bucket"],
                    risk_score=float(row["risk_score"]),
                    risk_level=row["risk_level"],
                    contributing_incident_count=int(row["contributing_incident_count"]),
                    last_calculated_at=_parse_timestamp(row.get("last_calculated_at")),
                )
            )
        if len(rows) < _PAGE_SIZE:
            return cells
        start += _PAGE_SIZE
