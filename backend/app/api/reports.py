import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from supabase import Client

from app.agents.verify_agent import process_report_verification
from app.core.areas import (
    COORDINATE_SOURCE_CLIENT,
    AreasUnavailable,
    RegionError,
    get_area_directory,
    in_diy,
)
from app.api.reports_public import clear_public_cache
from app.core.rate_limit import enforce_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.report import ReportCreate, ReportOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


def _verify_then_refresh_public_cache(report_id: str) -> None:
    """Jalankan verifikasi lalu kosongkan cache daftar/statistik publik, supaya perubahan status
    (menunggu -> terverifikasi/ditandai) langsung terlihat tanpa menunggu cache kedaluwarsa."""
    try:
        process_report_verification(report_id)
    finally:
        clear_public_cache()


@router.post("", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def submit_report(
    payload: ReportCreate,
    background_tasks: BackgroundTasks,
    supabase: Client = Depends(get_supabase),
    _rate_limit: None = Depends(enforce_rate_limit),
) -> ReportOut:
    """Terima laporan warga secara anonim dan simpan ke Supabase.

    Memenuhi REQ-F-001 (tanpa akun/identitas), REQ-F-002/003 (lokasi &
    waktu), REQ-F-004 (validasi lewat ReportCreate/Pydantic di level API,
    bukan cuma frontend), dan REQ-F-005 (status awal 'menunggu_verifikasi').
    Tidak ada field identitas pelapor yang diterima maupun disimpan
    (REQ-NF-120).

    Lokasi: jalur berjenjang (`kabkota_kode` + `kecamatan_kode` [+ `kelurahan_kode`] [+ `jalan`])
    divalidasi hierarkinya ke tabel `areas`, dan `location_text` disusun SERVER dari nama
    wilayah. Jalur lama (`location_text` saja) tetap diterima.

    Koordinat awal ditentukan SEKETIKA tanpa panggilan jaringan (REQ-NF-100): (1) titik dari
    klien bila ada dan di dalam DIY, (2) pusat kelurahan, (3) pusat kecamatan dari tabel areas.
    Presisi lebih baik via Mapbox (alamat jalan, atau teks lokasi jalur lama) dikerjakan di
    BACKGROUND TASK pada awal proses verifikasi (verify_agent._refine_location); gagal/di luar
    wilayah wajar -> koordinat awal tetap dipakai.

    Setelah laporan tersimpan, Report Verification & Clustering Agent
    (REQ-F-010..014) dijalankan sebagai background task — SETELAH respons
    ini dikirim, supaya konfirmasi submit tetap cepat (REQ-NF-100) dan
    proses AI benar-benar terjadi di latar belakang (REQ-NF-102).
    """
    record: dict = {"description": payload.description, "occurred_at": payload.occurred_at.isoformat()}
    if payload.incident_type_hint:  # hanya dikirim bila diisi, supaya basis data tanpa migrasi Fase E tetap bisa menerima laporan
        record["incident_type_hint"] = payload.incident_type_hint

    client_point = None
    if payload.latitude is not None and payload.longitude is not None and in_diy(payload.latitude, payload.longitude):
        client_point = (payload.latitude, payload.longitude)  # titik di luar DIY diabaikan, bukan ditolak

    if payload.kabkota_kode:
        try:
            region = get_area_directory(supabase).resolve_region(
                payload.kabkota_kode, payload.kecamatan_kode, payload.kelurahan_kode
            )
        except RegionError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
        except AreasUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Data wilayah sementara tidak dapat diambil, silakan coba lagi.",
            ) from None

        center = region.initial_coordinates()
        if client_point:
            latitude, longitude, source = (*client_point, COORDINATE_SOURCE_CLIENT)
        elif center:
            latitude, longitude, source = center
        else:
            latitude = longitude = source = None
        record.update(
            location_text=region.location_text(payload.jalan),
            kabkota_kode=region.kabkota.kode,
            kecamatan_kode=region.kecamatan.kode,
            kelurahan_kode=region.kelurahan.kode if region.kelurahan else None,
            jalan=payload.jalan,
            latitude=latitude,
            longitude=longitude,
            coordinate_source=source,
        )
    else:
        # Jalur lama: tanpa kolom wilayah. Koordinat dari klien bila ada; kalau tidak, NULL dan
        # background task mencoba geocoding teks lokasi (tidak lagi menahan respons ini).
        record.update(
            location_text=payload.location_text,
            latitude=client_point[0] if client_point else None,
            longitude=client_point[1] if client_point else None,
        )

    try:
        response = supabase.table("reports").insert(record).execute()
    except Exception as exc:  # noqa: BLE001 - error koneksi/Supabase wajib ditangani eksplisit, bukan silent fail
        # Bukan logger.exception: error database bisa memuat isi baris (teks
        # laporan). safe_error_summary hanya mencatat tipe error + kode aman.
        logger.error("Gagal menyimpan laporan ke Supabase: %s", safe_error_summary(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Laporan gagal disimpan, silakan coba lagi.",
        ) from exc

    if not response.data:
        logger.error("Supabase insert laporan tidak mengembalikan data")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Laporan gagal disimpan, silakan coba lagi.",
        )

    saved = response.data[0]
    # Laporan baru langsung tampil di histori publik (cache dikosongkan), lalu diperbarui lagi setelah verifikasi.
    clear_public_cache()
    background_tasks.add_task(_verify_then_refresh_public_cache, saved["id"])
    return ReportOut(id=saved["id"], status=saved["status"], created_at=saved["created_at"])
