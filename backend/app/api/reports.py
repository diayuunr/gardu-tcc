import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from supabase import Client

from app.agents.verify_agent import process_report_verification
from app.core.geocoding import geocode_location
from app.core.rate_limit import enforce_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.report import ReportCreate, ReportOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


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

    Kalau titik peta belum diisi, coba lengkapi otomatis lewat Mapbox
    Geocoding (dibatasi area Yogyakarta). Geocoding gagal/timeout/di luar
    area TIDAK menggagalkan laporan — koordinat tetap NULL kalau begitu.

    Setelah laporan tersimpan, Report Verification & Clustering Agent
    (REQ-F-010..014) dijalankan sebagai background task — SETELAH respons
    ini dikirim, supaya konfirmasi submit tetap cepat (REQ-NF-100) dan
    proses AI benar-benar terjadi di latar belakang (REQ-NF-102).
    """
    latitude = payload.latitude
    longitude = payload.longitude

    # KNOWN LIMITATION (latensi submit): geocoding Mapbox ini dipanggil
    # SINKRON di dalam request, jadi ikut menambah waktu respons (timeout
    # 3 dtk). Terukur: submit berurutan 2,8-4,5 dtk, dan sampai 18,9 dtk saat
    # 20 request bersamaan — di atas target REQ-NF-100 (<=3 dtk). Belum
    # dikerjakan; opsi ke depan: geocode di background task setelah insert.
    if latitude is None or longitude is None:
        geocoded = geocode_location(payload.location_text)
        if geocoded is not None:
            latitude, longitude = geocoded

    record = {
        "description": payload.description,
        "location_text": payload.location_text,
        "latitude": latitude,
        "longitude": longitude,
        "occurred_at": payload.occurred_at.isoformat(),
    }

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
    background_tasks.add_task(process_report_verification, saved["id"])
    return ReportOut(id=saved["id"], status=saved["status"], created_at=saved["created_at"])
