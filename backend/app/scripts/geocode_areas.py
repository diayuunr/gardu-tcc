"""CLI: periksa & isi koordinat pusat wilayah di tabel `areas` lewat Mapbox Geocoding.

Karena data wilayah umumnya sudah berkoordinat (CSV ekspor), skrip ini HANYA bekerja pada:
- baris yang lat/lng-nya KOSONG, atau
- baris yang koordinatnya DI LUAR DIY (tidak valid).
Koordinat yang sudah ada dan valid TIDAK PERNAH disentuh. Koordinat di luar DIY hanya diganti
bila hasil geocoding lolos validasi; selain itu dibiarkan dan dilaporkan.

Validasi hasil geocoding (tidak ada koordinat karangan): (1) di dalam DIY dan region ID-YO
(dijamin geocode_location), (2) cukup dekat dengan pusat INDUKNYA — kelurahan <=
`areas_geocode_max_kelurahan_distance_meters` dari kecamatan, kecamatan <=
`areas_geocode_max_kecamatan_distance_meters` dari kabupaten/kota. Induk diproses lebih dulu; bila
induk belum punya koordinat valid, anaknya dilaporkan "meragukan" (tidak diisi). Hasil yang tidak
lolos TIDAK ditulis, hanya dicantumkan di laporan untuk Anda tinjau.

Selain itu, koordinat yang ADA tetapi tampak jauh dari induknya (di atas ambang yang sama) hanya
dilaporkan sebagai "perlu ditinjau manual" — tidak pernah diubah.

Jalankan dari folder backend/, dengan .env terisi SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, MAPBOX_TOKEN:

    python -m app.scripts.geocode_areas --dry-run
    python -m app.scripts.geocode_areas
    python -m app.scripts.geocode_areas --limit 20
"""

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from supabase import Client

from app.core.areas import TINGKAT_KABKOTA, TINGKAT_KECAMATAN, TINGKAT_KELURAHAN, TINGKAT_ORDER, Area, in_diy
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.geo import haversine_meters
from app.core.geocoding import geocode_location
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

_PAGE_SIZE = 1000


@dataclass
class GeocodeReport:
    filled: list[str] = field(default_factory=list)  # kode yang diisi (atau akan diisi pada dry run)
    already_valid: int = 0
    doubtful: list[tuple[str, str, str]] = field(default_factory=list)  # (kode, nama, alasan) — tidak ditulis
    failed: list[tuple[str, str]] = field(default_factory=list)  # (kode, nama) — Mapbox tak menemukan
    unvalidated: list[str] = field(default_factory=list)  # kabkota diisi tanpa induk untuk memvalidasi
    suspicious_existing: list[tuple[str, str, int]] = field(default_factory=list)  # (kode, nama, jarak m) — tidak diubah
    write_errors: list[str] = field(default_factory=list)


def fetch_areas(supabase: Client) -> list[Area]:
    areas: list[Area] = []
    start = 0
    while True:
        rows = (
            execute_with_retry(
                supabase.table("areas")
                .select("kode,nama,tingkat,parent_kode,latitude,longitude")
                .order("kode")
                .range(start, start + _PAGE_SIZE - 1)
            ).data
            or []
        )
        areas.extend(
            Area(
                kode=row["kode"],
                nama=row["nama"],
                tingkat=row["tingkat"],
                parent_kode=row.get("parent_kode"),
                latitude=float(row["latitude"]) if row.get("latitude") is not None else None,
                longitude=float(row["longitude"]) if row.get("longitude") is not None else None,
            )
            for row in rows
        )
        if len(rows) < _PAGE_SIZE:
            return areas
        start += _PAGE_SIZE


def _query_text(area: Area, by_kode: dict[str, Area]) -> str:
    """Teks pencarian dari nama wilayah + induknya (konteks mencegah salah cocok ke desa senama)."""
    names = [area.label]
    parent = by_kode.get(area.parent_kode or "")
    while parent is not None:
        names.append(parent.label)
        parent = by_kode.get(parent.parent_kode or "")
    return ", ".join([*names, "Daerah Istimewa Yogyakarta"])


def _max_distance(area: Area, settings: Settings) -> int | None:
    if area.tingkat == TINGKAT_KELURAHAN:
        return settings.areas_geocode_max_kelurahan_distance_meters
    if area.tingkat == TINGKAT_KECAMATAN:
        return settings.areas_geocode_max_kecamatan_distance_meters
    return None


def _write_coordinates(supabase: Client, area: Area, point: tuple[float, float]) -> None:
    """Tulis dengan penjaga: hanya bila baris masih berkoordinat kosong / seperti yang kita baca
    (tidak menimpa koordinat yang berubah oleh proses lain di antara baca dan tulis)."""
    query = supabase.table("areas").update({"latitude": point[0], "longitude": point[1]}).eq("kode", area.kode)
    query = query.is_("latitude", "null") if area.latitude is None else query.eq("latitude", area.latitude)
    execute_with_retry(query)


def geocode_areas(
    supabase: Client,
    *,
    dry_run: bool,
    limit: int | None = None,
    geocode: Callable[[str], tuple[float, float] | None] = geocode_location,
    sleep: Callable[[float], None] = time.sleep,
    settings: Settings | None = None,
) -> GeocodeReport:
    settings = settings or get_settings()
    areas = fetch_areas(supabase)
    by_kode: dict[str, Area] = {area.kode: area for area in areas}
    report = GeocodeReport()

    def valid_center(area: Area | None) -> tuple[float, float] | None:
        return area.coordinates if area is not None else None

    # Tinjauan koordinat yang ada: jauh dari induk -> hanya dilaporkan.
    for area in areas:
        limit_m = _max_distance(area, settings)
        parent_center = valid_center(by_kode.get(area.parent_kode or ""))
        if area.coordinates and parent_center and limit_m:
            distance = int(haversine_meters(area.coordinates, parent_center))
            if distance > limit_m:
                report.suspicious_existing.append((area.kode, area.nama, distance))

    candidates = [area for area in areas if area.coordinates is None]  # kosong ATAU di luar DIY
    report.already_valid = len(areas) - len(candidates)
    candidates.sort(key=lambda a: (TINGKAT_ORDER.index(a.tingkat), a.kode))  # induk lebih dulu
    if limit is not None:
        candidates = candidates[:limit]

    for index, area in enumerate(candidates):
        if index > 0 and settings.areas_geocode_delay_seconds > 0:
            sleep(settings.areas_geocode_delay_seconds)
        try:
            point = geocode(_query_text(area, by_kode))
        except Exception as exc:  # noqa: BLE001 - satu baris gagal tidak menghentikan yang lain
            report.doubtful.append((area.kode, area.nama, f"error geocoding: {safe_error_summary(exc)}"))
            continue
        if point is None:
            report.failed.append((area.kode, area.nama))
            continue
        if not in_diy(*point):
            report.doubtful.append((area.kode, area.nama, "hasil di luar DIY"))
            continue

        limit_m = _max_distance(area, settings)
        if area.tingkat == TINGKAT_KABKOTA:
            report.unvalidated.append(area.kode)  # tidak ada induk untuk dibandingkan
        else:
            parent_center = valid_center(by_kode.get(area.parent_kode or ""))
            if parent_center is None:
                report.doubtful.append((area.kode, area.nama, "induk belum punya koordinat valid"))
                continue
            distance = int(haversine_meters(point, parent_center))
            if distance > (limit_m or 0):
                report.doubtful.append((area.kode, area.nama, f"{distance} m dari pusat induk (batas {limit_m} m)"))
                continue

        if not dry_run:
            try:
                _write_coordinates(supabase, area, point)
            except Exception as exc:  # noqa: BLE001
                report.write_errors.append(f"{area.kode}: {safe_error_summary(exc)}")
                continue
        by_kode[area.kode] = Area(area.kode, area.nama, area.tingkat, area.parent_kode, point[0], point[1])
        report.filled.append(area.kode)
    return report


def print_report(report: GeocodeReport, dry_run: bool) -> None:
    verb = "akan diisi" if dry_run else "diisi"
    logger.info("Sudah valid (tidak disentuh): %d", report.already_valid)
    logger.info("Koordinat %s: %d", verb, len(report.filled))
    for title, items in (
        ("Meragukan (TIDAK ditulis, tinjau manual)", [f"{k} {n}: {why}" for k, n, why in report.doubtful]),
        ("Tidak ditemukan Mapbox (TIDAK ditulis)", [f"{k} {n}" for k, n in report.failed]),
        ("Kabupaten/kota diisi tanpa validasi induk (periksa)", report.unvalidated),
        ("Koordinat ada tetapi jauh dari induk (TIDAK diubah, periksa)", [f"{k} {n}: {m} m" for k, n, m in report.suspicious_existing]),
        ("Gagal menulis", report.write_errors),
    ):
        if items:
            logger.warning("%s: %d", title, len(items))
            for item in items[:30]:
                logger.warning("  %s", item)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Periksa/isi koordinat wilayah yang kosong atau di luar DIY.")
    parser.add_argument("--dry-run", action="store_true", help="geocode & laporkan tanpa menulis")
    parser.add_argument("--limit", type=int, help="batasi jumlah baris yang diproses (hemat kuota Mapbox)")
    args = parser.parse_args(argv)

    if not get_settings().mapbox_token:
        logger.error("MAPBOX_TOKEN belum diisi di .env.")
        return 1
    try:
        report = geocode_areas(get_supabase(), dry_run=args.dry_run, limit=args.limit)
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1)
        logger.error("Pemeriksaan wilayah GAGAL: %s", safe_error_summary(exc))
        return 1
    print_report(report, args.dry_run)
    return 1 if report.write_errors else 0


if __name__ == "__main__":
    sys.exit(main())
