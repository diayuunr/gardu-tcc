import logging
import math
from dataclasses import dataclass, replace

import httpx

from app.core.config import get_settings
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

_DIRECTIONS_TIMEOUT_SECONDS = 5.0
# Profil "driving": rute kendaraan bermotor (klitih terjadi di jalan raya).
# Sistem TIDAK menampilkan navigasi turn-by-turn (SRS, di luar cakupan) — geometri
# rute hanya dipakai untuk memeriksa area yang dilintasi.
_DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving/{lon1},{lat1};{lon2},{lat2}"


class RouteNotFound(Exception):
    """Mapbox tidak menemukan rute antara kedua titik (pesan aman ditampilkan ke pengguna)."""


class RouteServiceUnavailable(Exception):
    """Layanan rute tidak bisa dipakai (token kosong, jaringan, timeout, respons aneh)."""


@dataclass(frozen=True)
class RouteStep:
    """Satu langkah navigasi Mapbox: nama jalan, jarak, durasi, dan geometri (lintang, bujur).
    Hanya dipakai untuk menamai jalan yang dilalui — bukan navigasi turn-by-turn (di luar cakupan SRS)."""

    name: str
    distance_m: float
    duration_s: float
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class RouteGeometry:
    """Rute hasil Mapbox: titik-titik (lintang, bujur) berurutan, jarak, dan durasi.

    `alternatives` = rute alternatif dari panggilan YANG SAMA (maks `route_max_alternatives`),
    tanpa alternatif bersarang; kosong bila Mapbox tidak menemukan alternatif."""

    points: tuple[tuple[float, float], ...]
    distance_m: float
    duration_s: float
    alternatives: tuple["RouteGeometry", ...] = ()
    steps: tuple[RouteStep, ...] = ()  # kosong bila Mapbox tak memberi langkah / langkahnya rusak


def fetch_route(
    origin: tuple[float, float], destination: tuple[float, float]
) -> RouteGeometry:
    """Ambil rute mengemudi asal -> tujuan dari Mapbox Directions API, beserta rute alternatif
    (maks `route_max_alternatives`) dalam SATU permintaan yang sama — tidak menambah panggilan.

    `origin`/`destination` berupa (latitude, longitude). Melempar RouteNotFound
    kalau tidak ada rute, RouteServiceUnavailable untuk semua kegagalan lain.
    PENTING: error httpx TIDAK di-chain (`from None`) dan TIDAK dicatat mentah —
    pesannya memuat URL lengkap termasuk `?access_token=...` (lihat safe_log.py).
    """
    settings = get_settings()
    if not settings.mapbox_token:
        logger.warning("MAPBOX_TOKEN belum diset, pemeriksaan rute tidak bisa dijalankan")
        raise RouteServiceUnavailable("MAPBOX_TOKEN belum diset")

    max_alternatives = max(0, settings.route_max_alternatives)
    url = _DIRECTIONS_URL.format(
        lon1=origin[1], lat1=origin[0], lon2=destination[1], lat2=destination[0]
    )
    try:
        response = httpx.get(
            url,
            params={
                "access_token": settings.mapbox_token,
                "geometries": "geojson",
                "overview": "full",
                "steps": "true",  # nama jalan per langkah
                "alternatives": "true" if max_alternatives > 0 else "false",
            },
            timeout=_DIRECTIONS_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Directions Mapbox gagal: %s", safe_error_summary(exc))
        raise RouteServiceUnavailable("permintaan ke Mapbox Directions gagal") from None

    code = payload.get("code")
    routes = payload.get("routes") or []
    if code in ("NoRoute", "NoSegment") or (code == "Ok" and not routes):
        raise RouteNotFound("Mapbox tidak menemukan rute")
    if code != "Ok":
        logger.warning("Directions Mapbox mengembalikan kode tak terduga: %s", code)
        raise RouteServiceUnavailable("respons Mapbox Directions tidak dikenali")

    primary = _parse_route(routes[0])
    return replace(primary, alternatives=_parse_alternatives(routes[1 : 1 + max_alternatives]))


def _parse_alternatives(raw_routes: list[dict]) -> tuple[RouteGeometry, ...]:
    """Alternatif yang rusak dilewati saja: rute utama tetap valid dan tetap dinilai."""
    alternatives: list[RouteGeometry] = []
    for raw in raw_routes:
        try:
            alternatives.append(_parse_route(raw))
        except RouteServiceUnavailable:
            continue
    return tuple(alternatives)


def _parse_route(route: dict) -> RouteGeometry:
    """Validasi ketat bentuk respons: koordinat harus angka terbatas & minimal 2 titik."""
    try:
        raw_points = route["geometry"]["coordinates"]
        points = tuple((float(lat), float(lon)) for lon, lat in raw_points)
        distance_m = float(route["distance"])
        duration_s = float(route["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Format respons Directions tidak terduga: %s", safe_error_summary(exc))
        raise RouteServiceUnavailable("format respons Mapbox Directions tidak terduga") from None

    finite = all(math.isfinite(value) for point in points for value in point)
    if len(points) < 2 or not finite or not (math.isfinite(distance_m) and math.isfinite(duration_s)):
        logger.warning("Geometri rute dari Directions tidak valid (titik=%d)", len(points))
        raise RouteServiceUnavailable("geometri rute tidak valid")

    return RouteGeometry(
        points=points, distance_m=distance_m, duration_s=max(0.0, duration_s), steps=_parse_steps(route)
    )


def _parse_steps(route: dict) -> tuple[RouteStep, ...]:
    """Langkah-langkah rute (nama jalan + geometri). Langkah tanpa panjang (mis. "arrive") dibuang.
    Bila ada langkah yang bentuknya rusak, SEMUA langkah dibuang (rute tetap valid, dinilai sebagai satu
    jalur tanpa nama) — lebih baik tanpa nama daripada nama yang salah tempat."""
    steps: list[RouteStep] = []
    try:
        for leg in route.get("legs") or []:
            for raw in leg.get("steps") or []:
                points = tuple((float(lat), float(lon)) for lon, lat in raw["geometry"]["coordinates"])
                distance_m, duration_s = float(raw["distance"]), float(raw["duration"])
                if not all(math.isfinite(v) for p in points for v in p) or not (
                    math.isfinite(distance_m) and math.isfinite(duration_s)
                ):
                    raise ValueError("langkah tidak terbatas")
                if distance_m <= 0 or len(points) < 2:
                    continue
                steps.append(RouteStep(str(raw.get("name") or "").strip(), distance_m, max(0.0, duration_s), points))
    except (KeyError, TypeError, ValueError, AttributeError):
        logger.warning("Langkah rute dari Directions tidak valid, nama jalan dilewati")
        return ()
    return tuple(steps)
