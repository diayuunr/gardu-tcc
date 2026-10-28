"""Data laporan untuk publik (landing): daftar anonim dan statistik agregat. REQ-F-042 / REQ-NF-120.

Daftar HANYA memuat nomor urut pendek, status, jam kejadian (dibulatkan per jam), kecamatan, dan kategori jenis
kejadian. Tidak ada deskripsi, jalan, koordinat, teks lokasi lengkap, UUID, atau petunjuk identitas pelapor.
Laporan yang ditandai duplikat/hoaks tidak ditampilkan (hanya dihitung di statistik)."""

import logging
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.agents.incident_index import normalize_category
from app.agents.moderation import public_number_label
from app.core.areas import AreaDirectory, get_directory_or_none, kecamatan_label
from app.core.config import get_settings
from app.core.db_retry import execute_with_retry
from app.core.rate_limit import enforce_public_reports_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.core.timeutil import to_wib
from app.schemas.report import PublicReportOut, PublicReportsOut, ReportStatsOut, ReportStatus, ReportStatusCounts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

PUBLIC_STATUSES = [ReportStatus.MENUNGGU_VERIFIKASI.value, ReportStatus.TERVERIFIKASI.value]
_UNKNOWN_REGION = "Daerah Istimewa Yogyakarta"

_lock = threading.Lock()
_list_cache: dict[tuple[int, int], tuple[float, PublicReportsOut]] = {}
_stats_cache: dict[str, tuple[float, ReportStatsOut]] = {}
_LIST_CACHE_MAX_ENTRIES = 200


def clear_public_cache() -> None:
    with _lock:
        _list_cache.clear()
        _stats_cache.clear()


def _region_label(row: dict, directory: AreaDirectory | None) -> str:
    """Kecamatan laporan: dari kode kecamatan, atau (laporan lama) kecamatan terdekat dari titiknya. Titik itu sendiri
    tidak pernah keluar dari fungsi ini."""
    if directory is None:
        return _UNKNOWN_REGION
    kecamatan = directory.get(row["kecamatan_kode"]) if row.get("kecamatan_kode") else None
    if kecamatan is None and row.get("latitude") is not None and row.get("longitude") is not None:
        kecamatan = directory.nearest_kecamatan(
            float(row["latitude"]), float(row["longitude"]), get_settings().risk_place_max_distance_meters
        )
    return kecamatan_label(directory, kecamatan) if kecamatan is not None else _UNKNOWN_REGION


def _hour_floor(value: str) -> datetime:
    return to_wib(datetime.fromisoformat(value)).replace(minute=0, second=0, microsecond=0)


def _to_public(row: dict, directory: AreaDirectory | None) -> PublicReportOut:
    return PublicReportOut(
        nomor=public_number_label(row.get("public_number")),
        status=row["status"],
        occurred_at=_hour_floor(row["occurred_at"]),
        wilayah=_region_label(row, directory),
        jenis=normalize_category(row.get("extracted_incident_type") or row.get("incident_type_hint")),
    )


def _cache_headers(response: Response) -> None:
    response.headers["Cache-Control"] = f"public, max-age={get_settings().public_reports_cache_seconds}"


@router.get("/public", response_model=PublicReportsOut, summary="Daftar laporan terbaru (publik, anonim)")
def public_reports(
    response: Response,
    limit: int | None = Query(None, ge=1, description="Jumlah per halaman (bawaan 20, maks 50)."),
    offset: int = Query(0, ge=0, description="Lewati sekian laporan (paginasi)."),
    supabase: Client = Depends(get_supabase),
    _rate_limit: None = Depends(enforce_public_reports_rate_limit),
) -> PublicReportsOut:
    """Laporan terbaru yang menunggu verifikasi atau terverifikasi, tanpa isi laporan. Hasil di-cache beberapa detik."""
    settings = get_settings()
    size = min(limit or settings.public_reports_default_page_size, settings.public_reports_max_page_size)
    key = (size, offset)
    with _lock:
        cached = _list_cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache_headers(response)
            return cached[1]

    try:
        result = execute_with_retry(
            supabase.table("reports")
            .select(
                "public_number,status,occurred_at,kecamatan_kode,latitude,longitude,extracted_incident_type,"
                "incident_type_hint",
                count="exact",
            )
            .in_("status", PUBLIC_STATUSES)
            .order("created_at", desc=True)
            .range(offset, offset + size - 1)
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Gagal memuat daftar laporan publik: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Data laporan sementara tidak dapat diambil.") from None

    directory = get_directory_or_none(supabase)
    payload = PublicReportsOut(
        total=result.count or 0, limit=size, offset=offset, items=[_to_public(row, directory) for row in result.data or []]
    )
    with _lock:
        if len(_list_cache) >= _LIST_CACHE_MAX_ENTRIES:
            _list_cache.clear()
        _list_cache[key] = (time.monotonic() + settings.public_reports_cache_seconds, payload)
    _cache_headers(response)
    return payload


def _count(supabase: Client, table: str, **filters: object) -> int:
    query = supabase.table(table).select("id", count="exact")
    for column, value in filters.items():
        query = query.eq(column, value)
    return execute_with_retry(query.limit(1)).count or 0


@router.get("/stats", response_model=ReportStatsOut, summary="Statistik laporan (publik, agregat)")
def report_stats(
    response: Response,
    supabase: Client = Depends(get_supabase),
    _rate_limit: None = Depends(enforce_public_reports_rate_limit),
) -> ReportStatsOut:
    """Total laporan, jumlah per status, insiden terverifikasi, dan data historis — angka saja, untuk landing."""
    settings = get_settings()
    with _lock:
        cached = _stats_cache.get("stats")
        if cached and cached[0] > time.monotonic():
            _cache_headers(response)
            return cached[1]

    try:
        counts = {s.value: _count(supabase, "reports", status=s.value) for s in ReportStatus}
        verified = _count(supabase, "incidents", status="terverifikasi")
        verified_seed = _count(supabase, "incidents", status="terverifikasi", is_seed_data=True)
        historical = _count(supabase, "incidents", is_seed_data=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("Gagal memuat statistik laporan: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Data statistik sementara tidak dapat diambil.") from None

    payload = ReportStatsOut(
        total_reports=sum(counts.values()),
        reports_by_status=ReportStatusCounts(**counts),
        verified_incidents=verified,
        verified_incidents_from_reports=max(0, verified - verified_seed),
        historical_incidents=historical,
    )
    with _lock:
        _stats_cache["stats"] = (time.monotonic() + settings.public_reports_cache_seconds, payload)
    _cache_headers(response)
    return payload
