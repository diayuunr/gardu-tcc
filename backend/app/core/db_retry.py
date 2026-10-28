import logging
from typing import Protocol

import httpx
from supabase import PostgrestAPIResponse

from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)


class Executable(Protocol):
    """Query builder Supabase apa pun (select/insert/update/upsert/delete/rpc) yang punya .execute()."""

    def execute(self) -> PostgrestAPIResponse: ...


def execute_with_retry(query: Executable) -> PostgrestAPIResponse:
    """Jalankan query Supabase; retry 1x kalau koneksi diputus server.

    Di bawah beban paralel (mis. 20 laporan sekaligus) satu client Supabase
    yang dipakai bersama banyak thread lewat HTTP/2 kadang diputus server
    (`httpx.RemoteProtocolError: Server disconnected`). Retry sekali sudah
    cukup untuk kasus itu; kegagalan kedua dibiarkan naik ke pemanggil
    (Verification/Risk Prediction Agent menelannya di try/except terluar,
    data mentah tetap aman).

    Catatan: kalau yang di-retry adalah INSERT dan server ternyata sudah
    memprosesnya sebelum koneksi putus, bisa terbentuk 1 baris ganda
    (langka; diterima sebagai trade-off opsi retry minimal).
    """
    try:
        return query.execute()
    except httpx.RemoteProtocolError as exc:
        logger.warning("Koneksi Supabase terputus (%s), retry 1x", safe_error_summary(exc))
        return query.execute()
