"""Data wilayah berjenjang DIY (kabupaten/kota > kecamatan > kelurahan/desa).

Sumber: tabel `areas` (diisi `app/scripts/load_areas.py`). Datanya statis (±500 baris), jadi
seluruhnya dimuat ke memori dan di-cache (`areas_cache_ttl_seconds`); membaca wilayah di
jalur submit laporan tidak menambah query database (REQ-NF-100) dan tidak ada panggilan jaringan.

Dipakai untuk: memvalidasi hierarki kode dari klien, MENYUSUN `location_text` di server
(teks dari klien tidak dipercaya), koordinat awal laporan dari pusat wilayah, dan GET /areas.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass

from supabase import Client

from app.core.config import get_settings
from app.core.db_retry import execute_with_retry
from app.core.geo import haversine_meters
from app.core.geocoding import YOGYAKARTA_BBOX
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

TINGKAT_KABKOTA = "kabkota"
TINGKAT_KECAMATAN = "kecamatan"
TINGKAT_KELURAHAN = "kelurahan"
TINGKAT_ORDER = (TINGKAT_KABKOTA, TINGKAT_KECAMATAN, TINGKAT_KELURAHAN)

# Format kode Kemendagri DIY per tingkat: 34.04 / 34.04.02 / 34.04.02.2001.
KODE_PATTERNS = {
    TINGKAT_KABKOTA: re.compile(r"^\d{2}\.\d{2}$"),
    TINGKAT_KECAMATAN: re.compile(r"^\d{2}\.\d{2}\.\d{2}$"),
    TINGKAT_KELURAHAN: re.compile(r"^\d{2}\.\d{2}\.\d{2}\.\d{4}$"),
}
KODE_REGEX = r"^\d{2}(\.\d{2}){1,2}(\.\d{4})?$"  # bentuk umum untuk validasi cepat di skema/parameter

COORDINATE_SOURCE_CLIENT = "client"
COORDINATE_SOURCE_GEOCODER = "geocoder"
_PAGE_SIZE = 1000


class RegionError(ValueError):
    """Kombinasi kode wilayah tidak valid; pesan Indonesia aman ditampilkan ke pengguna."""


class AreasUnavailable(Exception):
    """Data wilayah tidak bisa dimuat (database bermasalah) dan belum ada cache."""


def in_diy(latitude: float, longitude: float) -> bool:
    """Titik berada di dalam kotak pembatas DIY yang sama dengan geocoding."""
    min_lon, min_lat, max_lon, max_lat = YOGYAKARTA_BBOX
    return min_lat <= latitude <= max_lat and min_lon <= longitude <= max_lon


@dataclass(frozen=True)
class Area:
    kode: str
    nama: str
    tingkat: str
    parent_kode: str | None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def coordinates(self) -> tuple[float, float] | None:
        """Pusat wilayah, atau None bila kosong ATAU di luar DIY (data rusak tidak dipakai)."""
        if self.latitude is None or self.longitude is None or not in_diy(self.latitude, self.longitude):
            return None
        return self.latitude, self.longitude

    @property
    def label(self) -> str:
        """Nama untuk teks lokasi: awalan jenis wilayah ditambahkan agar jelas dibaca."""
        if self.tingkat == TINGKAT_KECAMATAN:
            return f"Kecamatan {self.nama}"
        if self.tingkat == TINGKAT_KELURAHAN:
            # Kode Kemendagri: segmen terakhir berawalan 1 = kelurahan, 2 = desa.
            kind = "Desa" if self.kode.rsplit(".", 1)[-1].startswith("2") else "Kelurahan"
            return f"{kind} {self.nama}"
        return self.nama  # nama kabkota sudah memuat "Kabupaten"/"Kota"


@dataclass(frozen=True)
class ResolvedRegion:
    kabkota: Area
    kecamatan: Area
    kelurahan: Area | None = None

    @property
    def anchor(self) -> Area:
        """Wilayah paling spesifik yang dipilih pelapor."""
        return self.kelurahan or self.kecamatan

    def location_text(self, jalan: str | None = None) -> str:
        """Teks lokasi yang DISUSUN SERVER, mis. "Jl. Kaliurang, Desa Caturtunggal, Kecamatan
        Depok, Kabupaten Sleman" — dari nama di tabel areas, bukan teks kiriman klien."""
        parts = [jalan, self.kelurahan.label if self.kelurahan else None, self.kecamatan.label, self.kabkota.label]
        return ", ".join(part for part in parts if part)

    def initial_coordinates(self) -> tuple[float, float, str] | None:
        """Koordinat awal INSTAN dari pusat wilayah: kelurahan dulu, lalu kecamatan (tanpa jaringan).
        Return (lat, lon, sumber) atau None bila keduanya tidak punya koordinat valid."""
        for area in (self.kelurahan, self.kecamatan):
            if area is not None and area.coordinates is not None:
                return (*area.coordinates, area.tingkat)
        return None


class AreaDirectory:
    """Indeks wilayah di memori (hanya-baca)."""

    def __init__(self, areas: list[Area]) -> None:
        self._by_kode = {area.kode: area for area in areas}
        # Hanya kecamatan dengan pusat valid yang bisa menamai sel grid.
        self._kecamatan_centers = sorted(
            ((area, area.coordinates) for area in areas if area.tingkat == TINGKAT_KECAMATAN and area.coordinates),
            key=lambda item: item[0].kode,
        )
        names = [area.nama.casefold() for area in areas if area.tingkat == TINGKAT_KECAMATAN]
        self._duplicate_kecamatan_names = {name for name in names if names.count(name) > 1}

    def nearest_kecamatan(self, latitude: float, longitude: float, max_distance_meters: float) -> Area | None:
        """Kecamatan dengan pusat TERDEKAT dari titik, atau None bila yang terdekat pun lebih jauh dari
        `max_distance_meters` (atau tak ada kecamatan berkoordinat). Imbang jarak dipecahkan dengan kode
        terkecil, jadi hasilnya deterministik. Tanpa jaringan: murni perhitungan di memori."""
        best: tuple[float, str, Area] | None = None
        for area, center in self._kecamatan_centers:
            distance = haversine_meters((latitude, longitude), center)
            if best is None or (distance, area.kode) < (best[0], best[1]):
                best = (distance, area.kode, area)
        if best is None or best[0] > max_distance_meters:
            return None
        return best[2]

    def place_name(self, kecamatan: Area) -> str:
        """Label publik kecamatan, mis. "Kec. Gondokusuman". Nama kembar antar kabupaten/kota (mis.
        Jetis di Kota Yogyakarta dan Bantul) diberi keterangan induk: "Kec. Jetis (Kota Yogyakarta)"."""
        label = f"Kec. {kecamatan.nama}"
        if kecamatan.nama.casefold() in self._duplicate_kecamatan_names:
            parent = self.get(kecamatan.parent_kode or "")
            if parent is not None:
                label += f" ({parent.nama})"
        return label

    def __len__(self) -> int:
        return len(self._by_kode)

    def get(self, kode: str) -> Area | None:
        return self._by_kode.get(kode)

    def find(self, tingkat: str | None = None, parent_kode: str | None = None) -> list[Area]:
        """Wilayah terurut nama, difilter tingkat dan/atau induk."""
        found = [
            area
            for area in self._by_kode.values()
            if (tingkat is None or area.tingkat == tingkat) and (parent_kode is None or area.parent_kode == parent_kode)
        ]
        return sorted(found, key=lambda area: (area.nama.casefold(), area.kode))

    def resolve_region(
        self, kabkota_kode: str, kecamatan_kode: str, kelurahan_kode: str | None = None
    ) -> ResolvedRegion:
        """Validasi hierarki ke tabel areas: tiap kode harus ada, bertingkat tepat, dan anak harus
        berada di bawah induk yang dipilih. Pesan error tidak memuat kode kiriman klien."""
        kabkota = self._expect(kabkota_kode, TINGKAT_KABKOTA, "Kabupaten/kota")
        kecamatan = self._expect(kecamatan_kode, TINGKAT_KECAMATAN, "Kecamatan")
        if kecamatan.parent_kode != kabkota.kode:
            raise RegionError("Kecamatan yang dipilih bukan bagian dari kabupaten/kota tersebut.")
        kelurahan = None
        if kelurahan_kode:
            kelurahan = self._expect(kelurahan_kode, TINGKAT_KELURAHAN, "Kelurahan/desa")
            if kelurahan.parent_kode != kecamatan.kode:
                raise RegionError("Kelurahan/desa yang dipilih bukan bagian dari kecamatan tersebut.")
        return ResolvedRegion(kabkota=kabkota, kecamatan=kecamatan, kelurahan=kelurahan)

    def _expect(self, kode: str, tingkat: str, label: str) -> Area:
        area = self.get(kode)
        if area is None:
            raise RegionError(f"{label} tidak ditemukan.")
        if area.tingkat != tingkat:
            raise RegionError(f"{label} yang dipilih tidak sesuai tingkatnya.")
        return area


def _row_to_area(row: dict) -> Area:
    def number(value: object) -> float | None:
        return float(value) if value is not None else None

    return Area(
        kode=row["kode"],
        nama=row["nama"],
        tingkat=row["tingkat"],
        parent_kode=row.get("parent_kode"),
        latitude=number(row.get("latitude")),
        longitude=number(row.get("longitude")),
    )


def load_area_directory(supabase: Client) -> AreaDirectory:
    """Baca seluruh tabel `areas` (dipaginasi). Error database dibiarkan naik ke pemanggil."""
    areas: list[Area] = []
    start = 0
    while True:
        response = execute_with_retry(
            supabase.table("areas")
            .select("kode,nama,tingkat,parent_kode,latitude,longitude")
            .order("kode")
            .range(start, start + _PAGE_SIZE - 1)
        )
        rows = response.data or []
        areas.extend(_row_to_area(row) for row in rows)
        if len(rows) < _PAGE_SIZE:
            return AreaDirectory(areas)
        start += _PAGE_SIZE


def kecamatan_label(directory: "AreaDirectory", kecamatan: Area) -> str:
    """Label kecamatan untuk pengguna, mis. "Kec. Depok, Kabupaten Sleman". Nama kembar ("Kec. Jetis (Kota
    Yogyakarta)") sudah memuat induknya, jadi tidak diulang."""
    label = directory.place_name(kecamatan)
    parent = directory.get(kecamatan.parent_kode or "")
    if parent is not None and "(" not in label:
        label = f"{label}, {parent.nama}"
    return label


def get_directory_or_none(supabase: Client) -> "AreaDirectory | None":
    """Direktori wilayah, atau None bila tak terbaca/kosong — untuk pemakai yang hanya butuh nama wilayah sebagai
    pelengkap (pencarian tempat, nama titik rute) dan tidak boleh gagal karenanya."""
    try:
        directory = get_area_directory(supabase)
    except AreasUnavailable:
        return None
    return directory if len(directory) else None


_cache_lock = threading.Lock()
_cache: dict[str, object] = {}  # {"directory": AreaDirectory, "expires": monotonic}


def reset_area_directory_cache() -> None:
    with _cache_lock:
        _cache.clear()


def get_area_directory(supabase: Client) -> AreaDirectory:
    """Direktori dari cache; dimuat ulang setelah TTL. Bila pemuatan ulang gagal, cache lama
    (kedaluwarsa) tetap dipakai — wilayah hampir statis, jadi lebih baik sedikit usang daripada
    submit laporan gagal. Tanpa cache sama sekali dan database gagal -> AreasUnavailable."""
    with _cache_lock:
        directory = _cache.get("directory")
        if directory is not None and float(_cache["expires"]) > time.monotonic():
            return directory  # type: ignore[return-value]

    try:
        fresh = load_area_directory(supabase)
    except Exception as exc:  # noqa: BLE001 - database bermasalah: pakai cache lama bila ada
        logger.error("Gagal memuat data wilayah: %s", safe_error_summary(exc))
        with _cache_lock:
            stale = _cache.get("directory")
        if stale is not None:
            return stale  # type: ignore[return-value]
        raise AreasUnavailable("data wilayah tidak tersedia") from None

    if len(fresh) == 0:
        # Tabel kosong = skrip load_areas belum dijalankan; jangan cache supaya langsung pulih sesudahnya.
        logger.warning("Tabel areas kosong: jalankan app.scripts.load_areas")
        return fresh
    with _cache_lock:
        _cache["directory"] = fresh
        _cache["expires"] = time.monotonic() + get_settings().areas_cache_ttl_seconds
    return fresh
