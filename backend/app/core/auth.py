"""Autentikasi panel moderasi (REQ-NF-123) dan token rahasia endpoint internal.

Moderator: header `Authorization: Bearer <JWT Supabase Auth>`. JWT DIVERIFIKASI ke Supabase Auth
(`auth.get_user(token)`), bukan sekadar didekode, lalu pengguna harus ada di tabel `moderators`. Token tidak
pernah dicatat di log. Pelapor warga tetap anonim — akun moderator adalah akun internal tim.

Internal: header `X-Internal-Token` dibandingkan dengan `INTERNAL_API_TOKEN` (waktu-konstan). Token kosong di
env = endpoint internal mati (404, tidak membocorkan keberadaannya).
"""

import hmac
import logging
from dataclasses import dataclass

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client
from supabase_auth.errors import AuthError

from app.core.config import get_settings
from app.core.db_retry import execute_with_retry
from app.core.rate_limit import enforce_internal_rate_limit, enforce_moderation_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)

_MAX_TOKEN_LENGTH = 4096
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}

# Skema keamanan resmi OpenAPI: Swagger (/docs) menampilkan tombol "Authorize". auto_error=False agar pesan 401 kita sendiri
# (bahasa Indonesia) yang dipakai.
_bearer_scheme = HTTPBearer(auto_error=False, description="Access token Supabase Auth milik moderator.")
_internal_scheme = APIKeyHeader(name="X-Internal-Token", auto_error=False, description="Token rahasia endpoint internal.")


@dataclass(frozen=True)
class Moderator:
    id: str  # moderators.id (dipakai sebagai jejak `reports.moderated_by`)
    user_id: str  # auth.users.id
    display_name: str


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    token = (credentials.credentials if credentials else "").strip()
    if not token or len(token) > _MAX_TOKEN_LENGTH:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Masuk sebagai moderator terlebih dahulu.", headers=_UNAUTHORIZED
        )
    return token


def get_current_moderator(
    _rate_limit: None = Depends(enforce_moderation_rate_limit),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    supabase: Client = Depends(get_supabase),
) -> Moderator:
    """401 bila token hilang/tidak valid/kedaluwarsa, 403 bila akun bukan moderator, 503 bila Supabase Auth mati."""
    token = _bearer_token(credentials)
    try:
        auth_response = supabase.auth.get_user(token)
        user = getattr(auth_response, "user", None)
    except AuthError:
        user = None  # token palsu, kedaluwarsa, atau sudah dicabut
    except (httpx.HTTPError, OSError) as exc:
        logger.error("Supabase Auth tidak dapat dihubungi saat verifikasi moderator: %s", safe_error_summary(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Layanan masuk sementara tidak tersedia, coba lagi."
        ) from None
    if user is None or not getattr(user, "id", None):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesi tidak valid atau sudah berakhir.", headers=_UNAUTHORIZED)

    try:
        response = execute_with_retry(
            supabase.table("moderators").select("id,user_id,display_name").eq("user_id", str(user.id)).limit(1)
        )
    except Exception as exc:  # noqa: BLE001 - kegagalan DB dipetakan ke 503, tanpa isi baris
        logger.error("Gagal memeriksa tabel moderators: %s", safe_error_summary(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Layanan sementara tidak tersedia, coba lagi.") from None
    if not response.data:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Akun ini tidak memiliki akses moderator.")
    row = response.data[0]
    return Moderator(id=str(row["id"]), user_id=str(row["user_id"]), display_name=str(row["display_name"]))


def require_internal_token(
    _rate_limit: None = Depends(enforce_internal_rate_limit),
    x_internal_token: str | None = Depends(_internal_scheme),
) -> None:
    """404 bila fitur dimatikan (token env kosong), 401 bila token salah/hilang."""
    expected = get_settings().internal_api_token
    if not expected:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    provided = (x_internal_token or "").encode()
    if not hmac.compare_digest(provided, expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token internal tidak valid.", headers={"WWW-Authenticate": "Token"})
