"""Indeks insiden terskor untuk analisis kedekatan Cek Rute (D3).

Memuat insiden yang ikut skor kerawanan (seed data + komunitas terverifikasi, REQ-F-022) yang
punya koordinat, lalu menyimpannya di indeks grid sederhana supaya pencarian "insiden dalam radius
R dari titik" tidak O(titik x semua insiden). Di-cache di memori `route_incident_cache_seconds` dan
di-invalidasi otomatis tiap kali skor dihitung ulang (insiden baru terverifikasi memicu hitung ulang).

PRIVASI (REQ-NF-120/121, REQ-F-042): indeks hanya hidup di memori server dan TIDAK PERNAH diserialisasi
ke respons. Satu-satunya teks yang dibawa adalah KATEGORI umum dari kosakata tetap (`normalize_category`):
`incident_type` di database bisa berupa teks bebas ("Klitih (korban pelajar SMP)") yang tidak boleh bocor.
"""

import logging
import math
import re
import threading
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from supabase import Client

from app.agents import risk_agent
from app.agents.risk_agent import time_bucket_of, to_wib
from app.core.config import get_settings
from app.core.db_retry import execute_with_retry
from app.core.geo import haversine_meters
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000
_METERS_PER_DEGREE = 111_320.0

# Kosakata kategori TETAP: urutan = prioritas (pola pertama yang cocok menang).
CATEGORY_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("klitih", re.compile(r"klitih")),
    ("bentrok antar kelompok", re.compile(r"bentrok|tawuran")),
    ("kejadian mencurigakan", re.compile(r"curiga")),  # sebelum "curi" agar "mencurigakan" tidak jadi pencurian
    ("begal/penodongan", re.compile(r"begal|todong|rampas|jambret|curi|pencurian")),
    ("penyerangan", re.compile(r"serang|nyerang|bacok|aniaya|eroyok|tusuk|sabet|gir|senjata")),
    ("pengrusakan", re.compile(r"rusak")),
)
CATEGORY_OTHER = "lainnya"


def normalize_category(raw: str | None) -> str:
    """Petakan `incident_type` (teks bebas) ke SATU kategori umum dari kosakata tetap. Teks yang tak
    cocok pola mana pun (mis. "Korban luka-luka") menjadi "lainnya" — rincian korban tidak ikut keluar."""
    text = (raw or "").casefold()
    return next((category for category, pattern in CATEGORY_RULES if pattern.search(text)), CATEGORY_OTHER)


@dataclass(frozen=True)
class IndexedIncident:
    ident: int  # nomor urut di indeks (bukan id database)
    latitude: float
    longitude: float
    occurred_at: datetime  # timezone-aware WIB
    bucket: str  # bucket jam kejadian (WIB)
    category: str  # kategori umum (kosakata tetap)


class IncidentIndex:
    """Indeks grid insiden. Sel grid berukuran `cell_meters` (bawaan 1,5 km)."""

    def __init__(self, incidents: Iterable[IndexedIncident], cell_meters: float = 1500.0) -> None:
        self._cell_deg = cell_meters / _METERS_PER_DEGREE
        self._cells: dict[tuple[int, int], list[IndexedIncident]] = defaultdict(list)
        count = 0
        for incident in incidents:
            self._cells[self._key(incident.latitude, incident.longitude)].append(incident)
            count += 1
        self._count = count

    def __len__(self) -> int:
        return self._count

    def _key(self, latitude: float, longitude: float) -> tuple[int, int]:
        return math.floor(latitude / self._cell_deg), math.floor(longitude / self._cell_deg)

    def _candidates(self, latitude: float, longitude: float, radius_m: float) -> Iterable[IndexedIncident]:
        row, col = self._key(latitude, longitude)
        lat_ring = math.ceil(radius_m / _METERS_PER_DEGREE / self._cell_deg)
        lon_ring = math.ceil(radius_m / (_METERS_PER_DEGREE * max(0.2, math.cos(math.radians(latitude)))) / self._cell_deg)
        for d_row in range(-lat_ring, lat_ring + 1):
            for d_col in range(-lon_ring, lon_ring + 1):
                yield from self._cells.get((row + d_row, col + d_col), ())

    def near(self, latitude: float, longitude: float, radius_m: float) -> list[tuple[IndexedIncident, float]]:
        """Insiden dalam `radius_m` dari titik, beserta jaraknya (meter)."""
        found: list[tuple[IndexedIncident, float]] = []
        for incident in self._candidates(latitude, longitude, radius_m):
            distance = haversine_meters((latitude, longitude), (incident.latitude, incident.longitude))
            if distance <= radius_m:
                found.append((incident, distance))
        return found

    def any_within(self, latitude: float, longitude: float, radius_m: float) -> bool:
        return any(
            haversine_meters((latitude, longitude), (i.latitude, i.longitude)) <= radius_m
            for i in self._candidates(latitude, longitude, radius_m)
        )


# ------------------------------------------------------------------ database + cache


def fetch_route_incidents(supabase: Client) -> list[IndexedIncident]:
    """Seed data + insiden komunitas terverifikasi yang punya koordinat (dipaginasi)."""
    incidents: list[IndexedIncident] = []
    start = 0
    while True:
        rows = (
            execute_with_retry(
                supabase.table("incidents")
                .select("latitude,longitude,incident_time,incident_type")
                .or_("is_seed_data.eq.true,status.eq.terverifikasi")
                .order("id")
                .range(start, start + _PAGE_SIZE - 1)
            ).data
            or []
        )
        for row in rows:
            if row.get("latitude") is None or row.get("longitude") is None:
                continue
            when = to_wib(datetime.fromisoformat(row["incident_time"]))
            incidents.append(
                IndexedIncident(
                    ident=len(incidents),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    occurred_at=when,
                    bucket=time_bucket_of(when),
                    category=normalize_category(row.get("incident_type")),
                )
            )
        if len(rows) < _PAGE_SIZE:
            return incidents
        start += _PAGE_SIZE


_lock = threading.Lock()
_cache: dict[str, object] = {}


def invalidate_incident_index() -> None:
    with _lock:
        _cache.clear()


def get_incident_index(supabase: Client) -> IncidentIndex:
    """Indeks dari cache; dimuat ulang setelah `route_incident_cache_seconds`. Bila pemuatan ulang gagal,
    indeks lama dipakai; tanpa indeks sama sekali, error dilempar ke pemanggil (API -> 502)."""
    with _lock:
        index = _cache.get("index")
        if index is not None and float(_cache["expires"]) > time.monotonic():
            return index  # type: ignore[return-value]

    settings = get_settings()
    try:
        fresh = IncidentIndex(fetch_route_incidents(supabase), cell_meters=settings.route_data_coverage_radius_meters)
    except Exception as exc:  # noqa: BLE001 - pakai indeks lama bila ada
        with _lock:
            stale = _cache.get("index")
        if stale is None:
            raise
        logger.error("Gagal memuat ulang indeks insiden, memakai salinan lama: %s", safe_error_summary(exc))
        return stale  # type: ignore[return-value]

    with _lock:
        _cache["index"] = fresh
        _cache["expires"] = time.monotonic() + settings.route_incident_cache_seconds
    return fresh


# Hitung ulang skor (otomatis tiap insiden terverifikasi, atau CLI) = data insiden berubah.
risk_agent.add_recalculation_listener(invalidate_incident_index)
