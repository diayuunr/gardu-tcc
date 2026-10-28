"""Pencarian tempat BERLAPIS untuk DIY — satu resolver untuk /geo/search DAN titik asal/tujuan teks di /route/check.

Cakupan POI Mapbox di Indonesia lemah (landmark populer sering 0 hasil atau salah cocok ke desa senama di
Jawa Tengah), jadi hasil digabung dari beberapa lapisan, urut prioritas:

    1. landmark   : daftar kurasi lokal (data/landmarks.json): instan, tanpa jaringan, alias/singkatan (UGM, YIA)
    2. photon     : Photon (OpenStreetMap, photon.komoot.io): sumber utama untuk sisanya; hanya hasil di DIY
    3. nominatim  : Nominatim (OpenStreetMap), karena Photon publik tidak stabil. HANYA untuk penyelesaian teks
                    akhir (`final=True`: asal/tujuan rute) dan autocomplete saat Photon gagal; maks 1 permintaan/detik
    4. wilayah    : nama kecamatan/kelurahan dari tabel areas (titik pusatnya); instan
    5. mapbox     : CADANGAN TERAKHIR, hanya bila lapisan di atas menghasilkan < `geo_mapbox_fallback_min_results`;
                    meminta 5 kandidat dan memilih yang PERTAMA valid di DIY (region ID-YO)

Lapisan dijalankan berurutan dan berhenti begitu `limit` terpenuhi (jadi query landmark tak menyentuh jaringan).
Duplikat (jarak < `geo_dedupe_distance_meters` DAN nama mirip) dibuang, yang berprioritas lebih tinggi menang.
Kegagalan lapisan jaringan TIDAK menjadi error: dilewati (Photon: sirkuit pemutus `geo_photon_cooldown_seconds`),
hasil ditandai `degraded` dan tidak di-cache. Cache LRU `geo_search_cache_seconds`.

PRIVASI: kata kunci pengguna hanya hidup di memori (kunci cache); tidak pernah dicatat di log (log error memakai
`safe_error_summary`, yang tidak memuat URL). Setiap hasil membawa `source` supaya klien tahu asal datanya.
"""

import difflib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx

from app.core.areas import AreaDirectory, in_diy
from app.core.config import get_settings
from app.core.geo import haversine_meters
from app.core.geocoding import (
    YOGYAKARTA_BBOX,
    YOGYAKARTA_PROXIMITY,
    valid_diy_point,
)
from app.core.landmarks import match_landmarks, normalize
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

SOURCE_LANDMARK = "landmark"
SOURCE_PHOTON = "photon"
SOURCE_NOMINATIM = "nominatim"
SOURCE_WILAYAH = "wilayah"
SOURCE_MAPBOX = "mapbox"

_TIMEOUT_SECONDS = 3.0
_MAPBOX_TYPES = "poi,address,neighborhood,locality,place,district"
_MAPBOX_CANDIDATES = 5


@dataclass(frozen=True)
class PlaceHit:
    label: str  # nama singkat, mis. "Tugu Yogyakarta"
    place_name: str  # nama lengkap, mis. "Universitas Gadjah Mada, Depok, Sleman"
    latitude: float
    longitude: float
    source: str = SOURCE_MAPBOX
    category: str | None = None


@dataclass
class _Run:
    """Keadaan satu pencarian: hasil terkumpul + apakah ada lapisan jaringan yang gagal."""

    limit: int
    hits: list[PlaceHit] = field(default_factory=list)
    degraded: bool = False
    photon_down: bool = False  # Photon dimatikan/sedang dijeda/gagal pada pencarian ini

    @property
    def full(self) -> bool:
        return len(self.hits) >= self.limit

    def add(self, candidates: list[PlaceHit]) -> None:
        threshold = get_settings().geo_dedupe_distance_meters
        for hit in candidates:
            if self.full:
                return
            if not any(_is_duplicate(hit, existing, threshold) for existing in self.hits):
                self.hits.append(hit)


# --------------------------------------------------------------------- dedupe


def _names_similar(a: str, b: str) -> bool:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na or difflib.SequenceMatcher(None, na, nb).ratio() >= 0.75


def _is_duplicate(hit: PlaceHit, existing: PlaceHit, threshold_m: float) -> bool:
    close = haversine_meters((hit.latitude, hit.longitude), (existing.latitude, existing.longitude)) < threshold_m
    return close and _names_similar(hit.label, existing.label)


# ------------------------------------------------------------- lapisan 1: landmark


def _landmark_hits(query: str, limit: int) -> list[PlaceHit]:
    # `place_name` sengaja hanya nama landmark: kecamatan "terdekat" dihitung dari titik tengah wilayah (bukan
    # batas administratif), jadi untuk tempat di perbatasan salah (uji nyata: UGM berlabel Gondokusuman, padahal
    # Depok/Sleman). Lebih baik tanpa wilayah daripada wilayah yang keliru.
    hits: list[PlaceHit] = []
    for landmark in match_landmarks(query, limit):
        hits.append(
            PlaceHit(
                label=landmark.nama,
                place_name=landmark.nama,
                latitude=landmark.latitude,
                longitude=landmark.longitude,
                source=SOURCE_LANDMARK,
                category=landmark.kategori,
            )
        )
    return hits


# --------------------------------------------------------------- lapisan 2: photon

_photon_lock = threading.Lock()
_photon_down_until = 0.0


def _photon_available() -> bool:
    settings = get_settings()
    with _photon_lock:
        return settings.geo_photon_enabled and time.monotonic() >= _photon_down_until


def _photon_failed() -> None:
    global _photon_down_until
    with _photon_lock:
        _photon_down_until = time.monotonic() + get_settings().geo_photon_cooldown_seconds


def _dedupe_parts(parts: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        if part and part.strip() and part.strip().casefold() not in seen:
            seen.add(part.strip().casefold())
            result.append(part.strip())
    return result


def _parse_photon(payload: object, limit: int) -> list[PlaceHit]:
    hits: list[PlaceHit] = []
    features = payload.get("features") if isinstance(payload, dict) else None
    for feature in features or []:
        try:
            longitude, latitude = (float(v) for v in feature["geometry"]["coordinates"])
            props = feature.get("properties") or {}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        name = (props.get("name") or "").strip()
        state = (props.get("state") or "").casefold()
        if not name or not in_diy(latitude, longitude):
            continue
        if state and "yogyakarta" not in state:  # state lain (mis. Central Java) = bukan DIY walau di dalam bbox
            continue
        # "Nama, Kecamatan/Kota, Kabupaten": city (kecamatan/kota) dan county (kabupaten), tanpa pengulangan nama.
        parts = _dedupe_parts([name, props.get("city") or props.get("district"), props.get("county")])
        hits.append(
            PlaceHit(
                label=name, place_name=", ".join(parts), latitude=latitude, longitude=longitude, source=SOURCE_PHOTON,
                category=props.get("osm_value") or None,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _photon_hits(query: str, limit: int, run: _Run) -> list[PlaceHit]:
    if not _photon_available():
        run.photon_down = True
        return []
    settings = get_settings()
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    try:
        response = httpx.get(
            settings.geo_photon_url,
            params={
                "q": query,
                "limit": min(15, limit * 3),  # sebagian akan disaring (di luar DIY) dan sebagian duplikat
                "lat": YOGYAKARTA_PROXIMITY[1],
                "lon": YOGYAKARTA_PROXIMITY[0],
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
            },
            headers={"User-Agent": settings.geo_photon_user_agent},
            timeout=settings.geo_photon_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # JANGAN log exc mentah / URL: memuat kata kunci pengguna (lihat app/core/safe_log.py).
        logger.warning("Photon gagal, dilewati %d dtk: %s", settings.geo_photon_cooldown_seconds, safe_error_summary(exc))
        _photon_failed()
        run.degraded = True
        run.photon_down = True
        return []
    return _parse_photon(payload, limit)


# ----------------------------------------------------------- lapisan 3: nominatim

_nominatim_lock = threading.Lock()
_nominatim_down_until = 0.0
_nominatim_next_slot = 0.0  # waktu paling awal permintaan Nominatim berikutnya (pembatas laju dalam proses)
_nominatim_cache_lock = threading.Lock()
_nominatim_cache: "OrderedDict[tuple[str, int], tuple[float, tuple[PlaceHit, ...]]]" = OrderedDict()
_sleep = time.sleep  # titik sambung untuk test


def _nominatim_acquire(max_wait: float) -> bool:
    """Ambil giliran permintaan (maks 1 per `geo_nominatim_min_interval_seconds`). Bila giliran berikutnya lebih jauh
    dari `max_wait` detik, TIDAK menunggu dan mengembalikan False (pemanggil melewati lapisan ini)."""
    global _nominatim_next_slot
    settings = get_settings()
    with _nominatim_lock:
        now = time.monotonic()
        if not settings.geo_nominatim_enabled or now < _nominatim_down_until:
            return False
        wait = max(0.0, _nominatim_next_slot - now)
        if wait > max_wait:
            return False
        _nominatim_next_slot = now + wait + settings.geo_nominatim_min_interval_seconds
    if wait > 0:
        _sleep(wait)
    return True


def _nominatim_failed() -> None:
    global _nominatim_down_until
    with _nominatim_lock:
        _nominatim_down_until = time.monotonic() + get_settings().geo_nominatim_cooldown_seconds


def _parse_nominatim(payload: object, limit: int) -> list[PlaceHit]:
    hits: list[PlaceHit] = []
    for item in payload if isinstance(payload, list) else []:
        try:
            latitude, longitude = float(item["lat"]), float(item["lon"])
            address = item.get("address") or {}
            name = str(item.get("name") or "").strip()
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        state = str(address.get("state") or "").casefold()
        if not name or not in_diy(latitude, longitude):
            continue
        if state and "yogyakarta" not in state:  # provinsi lain walau di dalam bbox (mis. Klaten)
            continue
        locality = next((address[k] for k in ("village", "suburb", "city_district", "town", "city") if address.get(k)), None)
        parts = _dedupe_parts([name, locality, address.get("county") or address.get("city")])
        hits.append(
            PlaceHit(
                label=name, place_name=", ".join(parts), latitude=latitude, longitude=longitude,
                source=SOURCE_NOMINATIM, category=item.get("type") or None,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _nominatim_hits(query: str, limit: int, run: _Run, max_wait: float) -> list[PlaceHit]:
    settings = get_settings()
    key = (" ".join(query.casefold().split()), limit)
    with _nominatim_cache_lock:
        cached = _nominatim_cache.get(key)
        if cached and cached[0] > time.monotonic():
            _nominatim_cache.move_to_end(key)
            return list(cached[1])
    if not _nominatim_acquire(max_wait):
        run.degraded = True  # lapisan dilewati (laju/jeda/mati): hasil mungkin kurang lengkap, jangan di-cache
        return []
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    try:
        response = httpx.get(
            settings.geo_nominatim_url,
            params={
                "q": query,
                "format": "jsonv2",
                "limit": min(10, limit * 3),
                "countrycodes": "id",
                "viewbox": f"{min_lon},{max_lat},{max_lon},{min_lat}",  # kiri,atas,kanan,bawah
                "bounded": 1,
                "addressdetails": 1,
                "accept-language": "id",
            },
            headers={"User-Agent": settings.geo_nominatim_user_agent},
            timeout=settings.geo_nominatim_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "Nominatim gagal, dilewati %d dtk: %s", settings.geo_nominatim_cooldown_seconds, safe_error_summary(exc)
        )
        _nominatim_failed()
        run.degraded = True
        return []
    hits = tuple(_parse_nominatim(payload, limit))
    with _nominatim_cache_lock:
        _nominatim_cache[key] = (time.monotonic() + settings.geo_nominatim_cache_seconds, hits)
        _nominatim_cache.move_to_end(key)
        while len(_nominatim_cache) > settings.geo_nominatim_cache_max_entries:
            _nominatim_cache.popitem(last=False)
    return list(hits)


# ------------------------------------------------------------- lapisan 4: wilayah


def _area_hits(query: str, limit: int, directory: AreaDirectory | None) -> list[PlaceHit]:
    if directory is None:
        return []
    normalized = normalize(query)
    tokens = normalized.split()
    if len(normalized) < 3:
        return []

    scored: list[tuple[float, int, str, object]] = []
    for area in directory.find():
        if area.coordinates is None:
            continue
        name = normalize(area.nama)
        if name == normalized:
            score = 100.0
        elif name.startswith(normalized):
            score = 90.0
        elif all(any(t.startswith(q) for t in name.split()) for q in tokens):
            score = 75.0
        else:
            continue
        level = {"kecamatan": 0, "kabkota": 1, "kelurahan": 2}[area.tingkat]
        scored.append((-score, level, area.nama, area))
    scored.sort(key=lambda item: item[:3])

    hits: list[PlaceHit] = []
    for _score, _level, _name, area in scored[:limit]:
        chain, current = [], area
        while current is not None:
            chain.append(directory.place_name(current) if current.tingkat == "kecamatan" else current.label)
            current = directory.get(current.parent_kode or "")
        hits.append(
            PlaceHit(
                label=directory.place_name(area) if area.tingkat == "kecamatan" else area.label,
                place_name=", ".join(chain),
                latitude=area.coordinates[0],
                longitude=area.coordinates[1],
                source=SOURCE_WILAYAH,
                category=area.tingkat,
            )
        )
    return hits


# ------------------------------------------------------------- lapisan 5: mapbox


def _parse_mapbox(payload: object, limit: int) -> list[PlaceHit]:
    hits: list[PlaceHit] = []
    for feature in (payload.get("features") if isinstance(payload, dict) else None) or []:
        point = valid_diy_point(feature) if isinstance(feature, dict) else None
        label = str(feature.get("text") or "").strip() if point else ""
        if point is None or not label:
            continue  # bukan DIY (mis. desa senama di ID-JT) atau rusak: coba kandidat berikutnya
        hits.append(
            PlaceHit(
                label=label, place_name=str(feature.get("place_name") or label).strip(),
                latitude=point[0], longitude=point[1], source=SOURCE_MAPBOX,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _mapbox_hits(query: str, limit: int, run: _Run) -> list[PlaceHit]:
    settings = get_settings()
    if not settings.mapbox_token:
        return []
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(query, safe='')}.json"
    try:
        response = httpx.get(
            url,
            params={
                "access_token": settings.mapbox_token,
                "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                "proximity": f"{YOGYAKARTA_PROXIMITY[0]},{YOGYAKARTA_PROXIMITY[1]}",
                "country": "id",
                "language": "id",
                "autocomplete": "true",
                "types": _MAPBOX_TYPES,
                "limit": _MAPBOX_CANDIDATES,
            },
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Pencarian tempat Mapbox gagal: %s", safe_error_summary(exc))
        run.degraded = True
        return []
    return _parse_mapbox(payload, limit)


# ------------------------------------------------------------------- cache LRU

_cache_lock = threading.Lock()
_cache: "OrderedDict[tuple[str, int, bool], tuple[float, tuple[PlaceHit, ...]]]" = OrderedDict()


def clear_place_cache() -> None:
    """Kosongkan cache dan reset sirkuit pemutus/pembatas laju Photon & Nominatim (dipakai test)."""
    global _photon_down_until, _nominatim_down_until, _nominatim_next_slot
    with _cache_lock:
        _cache.clear()
    with _photon_lock:
        _photon_down_until = 0.0
    with _nominatim_cache_lock:
        _nominatim_cache.clear()
    with _nominatim_lock:
        _nominatim_down_until = 0.0
        _nominatim_next_slot = 0.0


# ----------------------------------------------------------------------- API


@dataclass(frozen=True)
class SearchResult:
    hits: tuple[PlaceHit, ...]
    degraded: bool  # ada lapisan jaringan yang gagal: hasil mungkin kurang lengkap


def search(query: str, limit: int = 5, directory: AreaDirectory | None = None, *, final: bool = False) -> SearchResult:
    """Cari tempat di DIY lewat lapisan berprioritas. `query` sudah dirapikan pemanggil. Tidak pernah melempar
    exception akibat layanan eksternal; kegagalan ditandai lewat `degraded`.

    `final=True` = penyelesaian teks akhir (asal/tujuan rute), bukan autocomplete: Nominatim boleh dipakai dan
    menunggu giliran bila perlu. Pada autocomplete Nominatim hanya dipakai saat Photon gagal, tanpa menunggu."""
    settings = get_settings()
    key = (" ".join(query.casefold().split()), limit, final)
    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(key)
            return SearchResult(cached[1], degraded=False)

    run = _Run(limit=limit)
    run.add(_landmark_hits(query, limit))
    if not run.full:
        run.add(_photon_hits(query, limit, run))
    if not run.full and (final or run.photon_down):
        run.add(_nominatim_hits(query, limit, run, settings.geo_nominatim_max_wait_seconds if final else 0.0))
    if not run.full:
        run.add(_area_hits(query, limit, directory))
    if len(run.hits) < settings.geo_mapbox_fallback_min_results:
        run.add(_mapbox_hits(query, limit, run))

    hits = tuple(run.hits)
    if not run.degraded:  # hasil dari layanan yang sedang gagal jangan menempel di cache
        with _cache_lock:
            _cache[key] = (time.monotonic() + settings.geo_search_cache_seconds, hits)
            _cache.move_to_end(key)
            while len(_cache) > settings.geo_search_cache_max_entries:
                _cache.popitem(last=False)  # buang yang paling lama tidak dipakai
    return SearchResult(hits, run.degraded)


def search_places(query: str, limit: int = 5, directory: AreaDirectory | None = None) -> list[PlaceHit]:
    return list(search(query, limit, directory).hits)


def resolve_place(text: str, directory: AreaDirectory | None = None) -> tuple[float, float] | None:
    """Titik (lintang, bujur) untuk teks asal/tujuan: hasil TERATAS yang valid di DIY dari resolver yang SAMA
    dengan /geo/search; None bila tidak ada."""
    query = " ".join(text.split())
    if len(query) < 2:
        return None
    hits = search(query, 1, directory, final=True).hits
    return (hits[0].latitude, hits[0].longitude) if hits else None
