import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from supabase import Client

from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="Cek kesehatan layanan",
    responses={503: {"description": "Server hidup tetapi database tidak terjangkau."}},
)
def health_check(supabase: Client = Depends(get_supabase)):
    """Pastikan server hidup DAN koneksi Supabase berfungsi (satu query ringan, tanpa retry).

    200 `{"status": "ok", "database": "ok"}` bila semuanya sehat; 503
    `{"status": "degraded", "database": "unavailable"}` bila database tidak terjangkau
    (mis. URL/key Supabase salah — platform deploy bisa menahan rilis yang salah konfigurasi).
    Detail error (host, key, pesan driver) TIDAK PERNAH ikut ke respons maupun log.
    """
    try:
        supabase.table("risk_scores").select("id").limit(1).execute()
    except Exception as exc:  # noqa: BLE001 - health check tidak boleh melempar; kegagalan = 503 yang jelas
        logger.error("Health check: database tidak terjangkau: %s", safe_error_summary(exc))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "database": "unavailable"},
        )
    return {"status": "ok", "database": "ok"}
