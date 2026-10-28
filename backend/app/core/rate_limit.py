import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

_request_log: dict[str, deque[float]] = defaultdict(deque)


def _check_window(key: str, max_requests: int, window_seconds: int, detail: str) -> None:
    """Sliding window per `key`: tolak (429) kalau sudah `max_requests` dalam `window_seconds`."""
    now = time.monotonic()
    window = _request_log[key]

    while window and now - window[0] > window_seconds:
        window.popleft()

    if len(window) >= max_requests:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)

    window.append(now)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request) -> None:
    """Batasi jumlah laporan dari satu alamat IP dalam rentang waktu singkat (REQ-NF-122).

    Sliding window in-memory — cukup untuk prototipe single-instance.
    Kalau backend di-scale ke banyak instance, ganti dengan store bersama
    (mis. Redis) supaya limitnya konsisten lintas instance.
    """
    settings = get_settings()
    _check_window(
        _client_ip(request),
        settings.rate_limit_max_requests,
        settings.rate_limit_window_seconds,
        "Terlalu banyak laporan dikirim dari sumber ini, coba lagi nanti.",
    )


def enforce_route_check_rate_limit(request: Request) -> None:
    """Batas per-IP untuk Cek Rute Aman (tiap cek memakai kuota Mapbox & Gemini).

    Jatah TERPISAH dari laporan (kunci berawalan `route:` di dict yang sama, jadi
    reset `_request_log` di test tetap mencakup keduanya).
    """
    settings = get_settings()
    _check_window(
        f"route:{_client_ip(request)}",
        settings.route_check_rate_limit_max_requests,
        settings.route_check_rate_limit_window_seconds,
        "Terlalu banyak pemeriksaan rute dari sumber ini, coba lagi nanti.",
    )
