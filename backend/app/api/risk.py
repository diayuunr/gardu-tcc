import logging
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.agents.risk_agent import (
    WIB,
    fetch_risk_cells,
    lookup_risk_score,
    public_label,
    summarize_by_kecamatan,
    time_bucket_of,
)
from app.agents.risk_narrator import generate_risk_narrative
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.risk import RegionRiskOut, RiskCellOut, RiskHeatmapOut, RiskScoreOut, RiskSummaryOut, TimeBucket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["risk"])

# Cache pendek untuk heatmap: endpoint publik tanpa login (REQ-F-041) dan dimuat tiap
# pengunjung, sedangkan skor hanya berubah saat perhitungan ulang. Per proses, in-memory.
_HEATMAP_CACHE_TTL_SECONDS = 60.0
_heatmap_cache: dict[str, tuple[float, RiskHeatmapOut]] = {}
_heatmap_cache_lock = threading.Lock()
_summary_cache: dict[str, tuple[float, RiskSummaryOut]] = {}


@router.get("/score", response_model=RiskScoreOut)
def get_risk_score(
    lat: float = Query(..., ge=-90, le=90, description="Lintang titik yang ditanyakan"),
    lon: float = Query(..., ge=-180, le=180, description="Bujur titik yang ditanyakan"),
    at: datetime | None = Query(
        default=None,
        description="Waktu yang ditanyakan (default: sekarang). Tanpa zona waktu dianggap WIB.",
    ),
    include_narrative: bool = Query(
        default=False,
        description=(
            "true = sertakan penjelasan Gemini (`narrative`) untuk skor sedang/tinggi. "
            "Default false: jalur cepat untuk heatmap/banyak sel, tanpa memanggil Gemini. "
            "Pakai true hanya saat pengguna membuka detail SATU titik."
        ),
    ),
    supabase: Client = Depends(get_supabase),
) -> RiskScoreOut:
    """Skor kerawanan tersimpan untuk area yang memuat titik (lat, lon) pada
    rentang waktu `at` (REQ-F-020) — publik, tanpa login (REQ-F-041).

    Input divalidasi di sini (rentang lat/lon, format waktu, boolean) oleh
    FastAPI/Pydantic. `at` memilih bucket jam DAN tanggal untuk pengali musiman:
    skor dasar tersimpan dikali pengali Ramadan pada tanggal itu saat dibaca
    (dibatasi 10), lalu `risk_level` ditentukan dari skor akhir. Tanpa
    `include_narrative`, respons murni baca database (cepat, `narrative=null`).
    """
    moment = at or datetime.now(WIB)
    try:
        result = lookup_risk_score(supabase, lat, lon, moment)
    except Exception as exc:  # noqa: BLE001 - error database wajib ditangani eksplisit, bukan silent fail
        # Tanpa exc_info/pesan mentah (lihat app/core/safe_log.py).
        logger.error("Gagal mengambil skor kerawanan: %s", safe_error_summary(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Skor kerawanan sementara tidak dapat diambil, silakan coba lagi.",
        ) from exc

    # Narasi Gemini hanya menjelaskan angka di atas, dan HANYA bila diminta
    # eksplisit (satu titik, bukan heatmap). Tidak pernah melempar exception:
    # None kalau Gemini gagal/rate limit/tidak relevan.
    narrative = generate_risk_narrative(result) if include_narrative else None

    return RiskScoreOut(
        area_name=result.area_name,
        place_name=result.place_name,
        label=public_label(result.place_name, result.area_name),
        time_bucket=result.time_bucket,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        contributing_incident_count=result.contributing_incident_count,
        has_data=result.has_data,
        narrative=narrative,
    )


@router.get("/heatmap", response_model=RiskHeatmapOut)
def get_risk_heatmap(
    response: Response,
    time_bucket: TimeBucket | None = Query(
        default=None,
        description="Bucket jam WIB (dini_hari, pagi, siang, sore, malam). Default: bucket saat ini.",
    ),
    supabase: Client = Depends(get_supabase),
) -> RiskHeatmapOut:
    """Semua sel skor kerawanan untuk satu bucket jam, sebagai bahan heatmap Mapbox
    (REQ-F-040) — publik, tanpa login (REQ-F-041).

    Satu permintaan untuk seluruh sel (jalur cepat, tanpa Gemini); penjelasan per sel
    diambil terpisah lewat `/risk/score?include_narrative=true` saat pengguna membuka
    detail satu titik. `time_bucket` divalidasi FastAPI (nilai di luar daftar -> 422).
    Hasil di-cache singkat per bucket. Sel hanya memuat label area netral, pusat sel grid,
    dan angka agregat (REQ-F-042).
    """
    bucket = time_bucket or time_bucket_of(datetime.now(WIB))
    response.headers["Cache-Control"] = "public, max-age=30"

    with _heatmap_cache_lock:
        cached = _heatmap_cache.get(bucket)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        cells = fetch_risk_cells(supabase, bucket)
    except Exception as exc:  # noqa: BLE001 - error database wajib ditangani eksplisit, bukan silent fail
        # Tanpa exc_info/pesan mentah (lihat app/core/safe_log.py).
        logger.error("Gagal mengambil sel heatmap: %s", safe_error_summary(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Data peta kerawanan sementara tidak dapat diambil, silakan coba lagi.",
        ) from exc

    calculated_times = [cell.last_calculated_at for cell in cells if cell.last_calculated_at is not None]
    result = RiskHeatmapOut(
        time_bucket=bucket,
        cells=[
            RiskCellOut(
                area_name=cell.area_name,
                place_name=cell.place_name,
                label=public_label(cell.place_name, cell.area_name),
                latitude=cell.latitude,
                longitude=cell.longitude,
                risk_score=cell.risk_score,
                risk_level=cell.risk_level,
                contributing_incident_count=cell.contributing_incident_count,
            )
            for cell in sorted(cells, key=lambda c: c.risk_score, reverse=True)
        ],
        updated_at=max(calculated_times) if calculated_times else None,
    )
    with _heatmap_cache_lock:
        _heatmap_cache[bucket] = (time.monotonic() + _HEATMAP_CACHE_TTL_SECONDS, result)
    return result


@router.get("/summary", response_model=RiskSummaryOut)
def get_risk_summary(
    response: Response,
    time_bucket: TimeBucket | None = Query(
        default=None,
        description="Bucket jam WIB (dini_hari, pagi, siang, sore, malam). Default: bucket saat ini.",
    ),
    supabase: Client = Depends(get_supabase),
) -> RiskSummaryOut:
    """Ringkasan skor PER KECAMATAN untuk satu bucket jam, urut skor tertinggi — untuk daftar
    "wilayah teratas" tanpa mengulang nama kecamatan yang sama per sel. Publik, tanpa login.

    Tiap kecamatan: skor akhir tertinggi (sudah termasuk pengali musim) beserta levelnya, jumlah sel,
    dan total insiden kontribusi. Tidak ada koordinat sel maupun data individu (REQ-F-042). Sel yang
    belum punya kecamatan (belum dihitung ulang / terlalu jauh) tidak masuk daftar dan dihitung di
    `unassigned_cell_count`. Di-cache singkat per bucket.
    """
    bucket = time_bucket or time_bucket_of(datetime.now(WIB))
    response.headers["Cache-Control"] = "public, max-age=30"

    with _heatmap_cache_lock:
        cached = _summary_cache.get(bucket)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        cells = fetch_risk_cells(supabase, bucket)
    except Exception as exc:  # noqa: BLE001 - error database wajib ditangani eksplisit, bukan silent fail
        logger.error("Gagal mengambil ringkasan kecamatan: %s", safe_error_summary(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ringkasan kerawanan sementara tidak dapat diambil, silakan coba lagi.",
        ) from exc

    regions, unassigned = summarize_by_kecamatan(cells)
    calculated_times = [cell.last_calculated_at for cell in cells if cell.last_calculated_at is not None]
    result = RiskSummaryOut(
        time_bucket=bucket,
        regions=[
            RegionRiskOut(
                kecamatan_kode=region.kecamatan_kode,
                place_name=region.place_name,
                label=region.place_name,
                risk_score=region.risk_score,
                risk_level=region.risk_level,
                cell_count=region.cell_count,
                incident_count=region.incident_count,
            )
            for region in regions
        ],
        unassigned_cell_count=unassigned,
        updated_at=max(calculated_times) if calculated_times else None,
    )
    with _heatmap_cache_lock:
        _summary_cache[bucket] = (time.monotonic() + _HEATMAP_CACHE_TTL_SECONDS, result)
    return result
