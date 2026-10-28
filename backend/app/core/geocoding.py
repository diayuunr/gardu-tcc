import logging
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

# Bounding box longgar untuk Daerah Istimewa Yogyakarta (DIY):
# (min_lon, min_lat, max_lon, max_lat). Dipakai sebagai parameter `bbox` ke
# Mapbox (bias pencarian) DAN sebagai lapisan validasi kedua di bawah.
#
# CATATAN PENTING (ditemukan lewat tes nyata pakai token asli): bbox+proximity
# SAJA TIDAK CUKUP. Query seperti "Alun-Alun Kidul" atau "Tugu Yogyakarta"
# ternyata dicocokkan Mapbox ke desa bernama sama di Klaten (Jawa Tengah,
# BUKAN DIY) karena Klaten berbatasan langsung dan ikut masuk bbox longgar
# ini. Validasi utama karena itu memakai `region.short_code` dari field
# `context` respons Mapbox (kode ISO 3166-2 wilayah) — DIY = "ID-YO".
# Bbox tetap dipertahankan sebagai jaring pengaman kedua untuk hasil yang
# entah kenapa tidak punya info region di context.
YOGYAKARTA_BBOX = (110.00, -8.25, 110.85, -7.50)  # minLon, minLat, maxLon, maxLat
YOGYAKARTA_PROXIMITY = (110.3695, -7.7956)  # pusat Kota Yogyakarta (lon, lat)
YOGYAKARTA_REGION_SHORT_CODE = "ID-YO"

_GEOCODING_TIMEOUT_SECONDS = 3.0


def geocode_location(location_text: str) -> tuple[float, float] | None:
    """Ubah teks lokasi laporan jadi koordinat lewat Mapbox Geocoding API,
    dibatasi ke area Yogyakarta (REQ-F-002: input lokasi berupa nama
    jalan/area atau titik peta — fungsi ini melengkapi nama jalan/area
    dengan titik peta secara otomatis).

    Dirancang untuk TIDAK PERNAH melempar exception ke pemanggil: kalau
    MAPBOX_TOKEN belum diset, request ke Mapbox gagal/timeout, tidak ada
    hasil, atau hasilnya di luar area Yogyakarta, fungsi ini mengembalikan
    None. Pemanggil (submit_report) harus tetap menyimpan laporan dengan
    koordinat NULL pada semua kondisi itu — laporan tidak boleh ditolak
    hanya karena geocoding gagal.

    Return: (latitude, longitude) atau None.
    """
    settings = get_settings()
    if not settings.mapbox_token:
        logger.info("MAPBOX_TOKEN belum diset, lewati geocoding untuk laporan ini")
        return None

    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    encoded_query = quote(location_text, safe="")
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{encoded_query}.json"

    try:
        response = httpx.get(
            url,
            params={
                "access_token": settings.mapbox_token,
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                "proximity": f"{YOGYAKARTA_PROXIMITY[0]},{YOGYAKARTA_PROXIMITY[1]}",
                "country": "id",
                "limit": 1,
            },
            timeout=_GEOCODING_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # PENTING: JANGAN log `exc` mentah. Pesan httpx.HTTPStatusError memuat URL
        # LENGKAP termasuk `?access_token=...`. Teks lokasi (bisa berisi alamat
        # rumah) juga sengaja tidak dicatat. Lihat app/core/safe_log.py.
        logger.warning("Geocoding Mapbox gagal, koordinat dilewati: %s", safe_error_summary(exc))
        return None

    features = payload.get("features") or []
    if not features:
        logger.info("Mapbox tidak menemukan koordinat untuk sebuah lokasi laporan")
        return None

    feature = features[0]

    try:
        longitude, latitude = feature["center"]
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Format respons Mapbox tidak terduga: %s", safe_error_summary(exc))
        return None

    # Koordinat & place_name hasil diturunkan dari teks yang diketik pengguna (bisa
    # alamat rumah, mis. titik asal Cek Rute), jadi TIDAK dicatat di log — cukup
    # alasan penolakan dan kode region (bukan data pribadi).
    if not (min_lon <= longitude <= max_lon and min_lat <= latitude <= max_lat):
        logger.info("Hasil geocoding di luar bbox Yogyakarta, diabaikan")
        return None

    region_short_code = _extract_region_short_code(feature)
    if region_short_code is not None and region_short_code != YOGYAKARTA_REGION_SHORT_CODE:
        logger.info(
            "Hasil geocoding cocok ke region %s (bukan %s), diabaikan",
            region_short_code,
            YOGYAKARTA_REGION_SHORT_CODE,
        )
        return None

    return (latitude, longitude)


_AREA_NAME_CACHE_MAX_ENTRIES = 512
# Nama area per titik pusat sel grid. Hanya hasil SUKSES yang disimpan: kegagalan
# sementara (timeout/429) tidak boleh "menempel" jadi None selamanya.
_area_name_cache: dict[tuple[float, float], str] = {}


def describe_area(latitude: float, longitude: float) -> str | None:
    """Nama area tingkat kecamatan/desa (mis. "Kotagede") untuk sebuah titik, lewat
    Mapbox reverse geocoding — supaya saran "area yang sebaiknya dihindari"
    (REQ-F-032) terbaca warga, bukan sekadar koordinat grid.

    Sengaja `types=locality` (level kecamatan/desa), BUKAN alamat/jalan/kelurahan:
    yang dikirim hanya koordinat pusat sel grid (data publik), tidak ada teks
    pengguna, dan nama yang kembali tidak menyebut alamat siapa pun (REQ-F-042).

    TIDAK PERNAH melempar exception; None kalau token kosong, gagal, tidak ada
    hasil, atau hasilnya bukan wilayah DIY. Pemanggil harus siap tanpa nama.
    """
    cache_key = (round(latitude, 4), round(longitude, 4))
    cached = _area_name_cache.get(cache_key)
    if cached is not None:
        return cached

    settings = get_settings()
    if not settings.mapbox_token:
        return None

    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{longitude},{latitude}.json"
    try:
        response = httpx.get(
            url,
            params={"access_token": settings.mapbox_token, "types": "locality", "language": "id", "limit": 1},
            timeout=_GEOCODING_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        features = response.json().get("features") or []
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        # Sama seperti geocode_location: JANGAN log `exc` mentah (URL memuat token).
        logger.warning("Reverse geocoding Mapbox gagal, nama area dilewati: %s", safe_error_summary(exc))
        return None

    if not features:
        return None
    feature = features[0]
    name = feature.get("text")
    region_short_code = _extract_region_short_code(feature)
    if not isinstance(name, str) or not name.strip():
        return None
    if region_short_code is not None and region_short_code != YOGYAKARTA_REGION_SHORT_CODE:
        return None

    if len(_area_name_cache) >= _AREA_NAME_CACHE_MAX_ENTRIES:
        del _area_name_cache[next(iter(_area_name_cache))]  # buang yang paling lama masuk
    _area_name_cache[cache_key] = name.strip()
    return name.strip()


def _extract_region_short_code(feature: dict) -> str | None:
    """Ambil kode ISO 3166-2 region (mis. "ID-YO") dari field `context`
    respons Mapbox. Return None kalau context tidak punya entri region sama
    sekali — di kondisi itu kita jatuh balik ke validasi bbox saja.
    """
    for entry in feature.get("context", []):
        entry_id = entry.get("id", "")
        if entry_id.startswith("region") and entry.get("short_code"):
            return entry["short_code"]
    return None
