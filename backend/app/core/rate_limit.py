import hashlib
import hmac
import ipaddress
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.core.config import get_settings

# Kunci = HMAC(IP) dengan garam acak PER PROSES, bukan IP mentah: alamat tidak pernah tersimpan
# maupun muncul di log (REQ-NF-120/122), dan hash tidak bisa dibalik tanpa garam yang hanya
# hidup di memori. Konsekuensinya limit mulai dari nol saat proses restart (diterima).
_HASH_SALT = secrets.token_bytes(16)
_request_log: dict[str, deque[float]] = defaultdict(deque)

# Cegah dict tumbuh tanpa batas oleh banyak IP berbeda: lewat ambang ini, entri yang sudah
# kedaluwarsa dibuang.
_PURGE_THRESHOLD = 5000
_LONGEST_WINDOW_SECONDS = 3600


def _purge_expired(now: float) -> None:
    for key in [k for k, window in _request_log.items() if not window or now - window[-1] > _LONGEST_WINDOW_SECONDS]:
        del _request_log[key]


def _check_window(key: str, max_requests: int, window_seconds: int, detail: str) -> None:
    """Sliding window per `key`: tolak (429) kalau sudah `max_requests` dalam `window_seconds`."""
    now = time.monotonic()
    if len(_request_log) > _PURGE_THRESHOLD:
        _purge_expired(now)
    window = _request_log[key]

    while window and now - window[0] > window_seconds:
        window.popleft()

    if len(window) >= max_requests:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)

    window.append(now)


def _parse_ip(raw: str) -> str | None:
    """Alamat IP valid dari satu entri X-Forwarded-For (boleh berisi port), selain itu None."""
    candidate = raw.strip()
    if candidate.startswith("[") and "]" in candidate:  # [::1]:1234
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1:  # 1.2.3.4:5678
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _normalize(ip: str) -> str:
    """IPv6 digabung per /64: satu host biasanya memegang seluruh /64, jadi berganti alamat di
    dalamnya tidak boleh menghindari limit."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address)


def _client_ip(request: Request) -> str:
    """IP klien. Di belakang proxy tepercaya (`TRUST_PROXY_HEADERS=true`) = entri VALID paling kiri
    di X-Forwarded-For (edge Railway menimpa header ini, jadi klien tidak bisa memalsukannya);
    entri rusak dilewati. Tanpa proxy tepercaya, header diabaikan sama sekali dan dipakai alamat
    koneksi langsung — kalau tidak, siapa pun bisa menghindari limit dengan mengirim header palsu."""
    peer = request.client.host if request.client else "unknown"
    if get_settings().trust_proxy_headers:
        for entry in request.headers.get("x-forwarded-for", "").split(","):
            parsed = _parse_ip(entry)
            if parsed:
                return parsed
    return peer


def _rate_limit_key(request: Request, scope: str = "") -> str:
    digest = hmac.new(_HASH_SALT, _normalize(_client_ip(request)).encode(), hashlib.sha256).hexdigest()[:32]
    return f"{scope}{digest}"


def enforce_rate_limit(request: Request) -> None:
    """Batasi jumlah laporan dari satu alamat IP dalam rentang waktu singkat (REQ-NF-122).

    Sliding window in-memory — cukup untuk prototipe single-instance.
    Kalau backend di-scale ke banyak instance, ganti dengan store bersama
    (mis. Redis) supaya limitnya konsisten lintas instance.
    """
    settings = get_settings()
    _check_window(
        _rate_limit_key(request),
        settings.rate_limit_max_requests,
        settings.rate_limit_window_seconds,
        "Terlalu banyak laporan dikirim dari sumber ini, coba lagi nanti.",
    )


def enforce_geo_rate_limit(request: Request) -> None:
    """Batas per-IP untuk pencarian tempat/autocomplete (tiap panggilan memakai kuota Mapbox). Longgar
    dibanding cek rute karena autocomplete memanggil beberapa kali per ketikan, tapi tetap terbatas."""
    settings = get_settings()
    _check_window(
        _rate_limit_key(request, "geo:"),
        settings.geo_search_rate_limit_max_requests,
        settings.geo_search_rate_limit_window_seconds,
        "Terlalu banyak pencarian tempat dari sumber ini, coba lagi sebentar lagi.",
    )


def enforce_route_check_rate_limit(request: Request) -> None:
    """Batas per-IP untuk Cek Rute Aman (tiap cek memakai kuota Mapbox & Gemini).

    Jatah TERPISAH dari laporan (kunci berawalan `route:` di dict yang sama, jadi
    reset `_request_log` di test tetap mencakup keduanya).
    """
    settings = get_settings()
    _check_window(
        _rate_limit_key(request, "route:"),
        settings.route_check_rate_limit_max_requests,
        settings.route_check_rate_limit_window_seconds,
        "Terlalu banyak pemeriksaan rute dari sumber ini, coba lagi nanti.",
    )


def enforce_public_reports_rate_limit(request: Request) -> None:
    """Batas per-IP untuk daftar/statistik laporan publik (data agregat, di-cache server)."""
    settings = get_settings()
    _check_window(
        _rate_limit_key(request, "public:"),
        settings.public_reports_rate_limit_max_requests,
        settings.public_reports_rate_limit_window_seconds,
        "Terlalu banyak permintaan dari sumber ini, coba lagi sebentar lagi.",
    )


def enforce_moderation_rate_limit(request: Request) -> None:
    """Batas per-IP untuk /moderation/* — dihitung SEBELUM token diperiksa, jadi tebak-tebakan token pun terbatas."""
    settings = get_settings()
    _check_window(
        _rate_limit_key(request, "moderation:"),
        settings.moderation_rate_limit_max_requests,
        settings.moderation_rate_limit_window_seconds,
        "Terlalu banyak permintaan dari sumber ini, coba lagi sebentar lagi.",
    )


def enforce_internal_rate_limit(request: Request) -> None:
    """Batas per-IP untuk /internal/* (juga membatasi tebakan token rahasia)."""
    settings = get_settings()
    _check_window(
        _rate_limit_key(request, "internal:"),
        settings.internal_rate_limit_max_requests,
        settings.internal_rate_limit_window_seconds,
        "Terlalu banyak permintaan dari sumber ini, coba lagi sebentar lagi.",
    )
