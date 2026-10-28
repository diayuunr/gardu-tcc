"""CLI: muat data wilayah (kabkota > kecamatan > kelurahan) dari CSV ke tabel `areas`.

Sumber: backend/data/areas_rows.csv (ekspor Supabase). Header yang diharapkan:

    area,lat,lng,kode,nama,tingkat,parent_kode

- Wajib: kode, nama, tingkat, parent_kode, lat, lng (header). Isi lat/lng boleh kosong per baris
  (nanti diisi `app/scripts/geocode_areas.py`).
- `area` = label lama untuk skor risiko di backend sebelumnya. Disimpan apa adanya bila ada,
  TIDAK pernah menjadi syarat (kolom boleh tidak ada, nilainya boleh kosong).

Validasi SEBELUM menulis apa pun (satu kesalahan = tidak ada yang ditulis, exit code 1):
format kode sesuai tingkat, tingkat dikenal, kode tidak kembar, nama tidak kosong, induk ada di
file dan tingkatnya tepat serta kode anak diawali kode induk, kabkota tanpa induk, lat/lng
berpasangan dan numerik. Koordinat di luar DIY TIDAK ditolak (diperingatkan): itu tugas
geocode_areas untuk memeriksa/menggantinya.

Idempoten: upsert berdasarkan `kode`; dijalankan dua kali hasilnya sama. Koordinat yang SUDAH
ada di database tidak dikosongkan bila CSV-nya kosong untuk baris itu.

Jalankan dari folder backend/, dengan .env terisi SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY:

    python -m app.scripts.load_areas --dry-run     # validasi & ringkasan saja
    python -m app.scripts.load_areas               # muat ke Supabase
    python -m app.scripts.load_areas --csv data/lain.csv
"""

import argparse
import csv
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from supabase import Client

from app.core.areas import KODE_PATTERNS, TINGKAT_KABKOTA, TINGKAT_KECAMATAN, TINGKAT_KELURAHAN, TINGKAT_ORDER, in_diy
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "areas_rows.csv"
REQUIRED_COLUMNS = ("kode", "nama", "tingkat", "parent_kode", "lat", "lng")
_PARENT_TINGKAT = {TINGKAT_KECAMATAN: TINGKAT_KABKOTA, TINGKAT_KELURAHAN: TINGKAT_KECAMATAN}
_CHUNK_SIZE = 200
_MAX_ERRORS_SHOWN = 25


@dataclass(frozen=True)
class AreaRow:
    kode: str
    nama: str
    tingkat: str
    parent_kode: str | None
    latitude: float | None
    longitude: float | None
    area: str | None


@dataclass(frozen=True)
class CsvResult:
    rows: list[AreaRow]
    errors: list[str]
    warnings: list[str]


def _number(raw: str) -> float | None:
    raw = (raw or "").strip()
    return float(raw) if raw else None


def read_areas_csv(path: Path) -> CsvResult:
    """Baca & validasi CSV. Tidak menyentuh database."""
    errors: list[str] = []
    warnings: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [name.strip() for name in (reader.fieldnames or [])]
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            return CsvResult([], [f"Header CSV kurang kolom: {', '.join(missing)} (ada: {', '.join(header)})"], [])
        raw_rows = list(reader)

    rows: list[AreaRow] = []
    seen: dict[str, int] = {}
    for line, row in enumerate(raw_rows, start=2):  # baris 1 = header
        if None in row:  # DictReader menaruh nilai berlebih di bawah kunci None
            errors.append(f"baris {line}: jumlah kolom melebihi header")
            continue
        raw = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        kode, tingkat = raw["kode"], raw["tingkat"]
        where = f"baris {line} ({kode or 'tanpa kode'})"
        if tingkat not in KODE_PATTERNS:
            errors.append(f"{where}: tingkat '{tingkat}' tidak dikenal")
            continue
        if not KODE_PATTERNS[tingkat].match(kode):
            errors.append(f"{where}: format kode tidak sesuai tingkat {tingkat}")
            continue
        if kode in seen:
            errors.append(f"{where}: kode kembar dengan baris {seen[kode]}")
            continue
        seen[kode] = line
        if not raw["nama"]:
            errors.append(f"{where}: nama kosong")
            continue
        try:
            latitude, longitude = _number(raw["lat"]), _number(raw["lng"])
        except ValueError:
            errors.append(f"{where}: lat/lng bukan angka")
            continue
        if (latitude is None) != (longitude is None):
            errors.append(f"{where}: lat dan lng harus terisi berpasangan")
            continue
        if latitude is not None and not in_diy(latitude, longitude):
            warnings.append(f"{where}: koordinat di luar DIY (geocode_areas akan memeriksanya)")
        rows.append(
            AreaRow(
                kode=kode,
                nama=" ".join(raw["nama"].split()),
                tingkat=tingkat,
                parent_kode=raw["parent_kode"] or None,
                latitude=latitude,
                longitude=longitude,
                area=raw.get("area") or None,
            )
        )

    by_kode = {row.kode: row for row in rows}
    for row in rows:
        where = f"{row.kode}"
        if row.tingkat == TINGKAT_KABKOTA:
            if row.parent_kode:
                errors.append(f"{where}: kabupaten/kota tidak boleh punya induk")
            continue
        parent = by_kode.get(row.parent_kode or "")
        if parent is None:
            errors.append(f"{where}: induk '{row.parent_kode}' tidak ada di file")
        elif parent.tingkat != _PARENT_TINGKAT[row.tingkat]:
            errors.append(f"{where}: induk '{parent.kode}' bertingkat {parent.tingkat}, seharusnya {_PARENT_TINGKAT[row.tingkat]}")
        elif not row.kode.startswith(parent.kode + "."):
            errors.append(f"{where}: kode tidak diawali kode induk '{parent.kode}'")

    if not rows and not errors:
        errors.append("CSV tidak berisi baris data")
    return CsvResult(rows, errors, warnings)


def _payload(row: AreaRow, *, with_coordinates: bool) -> dict:
    data = {"kode": row.kode, "nama": row.nama, "tingkat": row.tingkat, "parent_kode": row.parent_kode, "area": row.area}
    if with_coordinates:
        data.update(latitude=row.latitude, longitude=row.longitude)
    return data


def upsert_areas(supabase: Client, rows: list[AreaRow]) -> int:
    """Upsert per tingkat (induk lebih dulu, karena FK parent_kode). Baris tanpa koordinat dikirim
    TANPA kolom latitude/longitude supaya koordinat yang sudah ada di database tidak terhapus."""
    written = 0
    for tingkat in TINGKAT_ORDER:
        level_rows = [row for row in rows if row.tingkat == tingkat]
        for with_coordinates in (True, False):
            group = [row for row in level_rows if (row.latitude is not None) == with_coordinates]
            for start in range(0, len(group), _CHUNK_SIZE):
                chunk = [_payload(row, with_coordinates=with_coordinates) for row in group[start : start + _CHUNK_SIZE]]
                execute_with_retry(supabase.table("areas").upsert(chunk, on_conflict="kode"))
                written += len(chunk)
    return written


def summarize(rows: list[AreaRow]) -> list[str]:
    per_level = Counter(row.tingkat for row in rows)
    without_coordinates = sum(1 for row in rows if row.latitude is None)
    lines = [f"  {tingkat:<10} {per_level.get(tingkat, 0):>4}" for tingkat in TINGKAT_ORDER]
    lines.append(f"  {'total':<10} {len(rows):>4}  (tanpa koordinat: {without_coordinates})")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Muat data wilayah dari CSV ke tabel areas.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help=f"path CSV (bawaan: {DEFAULT_CSV.name})")
    parser.add_argument("--dry-run", action="store_true", help="validasi & ringkas saja, tanpa menulis")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        logger.error("File CSV tidak ditemukan: %s", args.csv)
        return 1
    result = read_areas_csv(args.csv)

    for warning in result.warnings[:_MAX_ERRORS_SHOWN]:
        logger.warning(warning)
    if result.errors:
        logger.error("CSV tidak valid, TIDAK ada yang ditulis (%d kesalahan):", len(result.errors))
        for error in result.errors[:_MAX_ERRORS_SHOWN]:
            logger.error("  %s", error)
        if len(result.errors) > _MAX_ERRORS_SHOWN:
            logger.error("  ... dan %d lainnya", len(result.errors) - _MAX_ERRORS_SHOWN)
        return 1

    logger.info("CSV valid:")
    for line in summarize(result.rows):
        logger.info(line)
    if args.dry_run:
        logger.info("DRY RUN: tidak ada yang ditulis ke database.")
        return 0

    try:
        written = upsert_areas(get_supabase(), result.rows)
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1)
        logger.error("Gagal menulis ke tabel areas (migrasi 20260922000000 sudah dijalankan?): %s", safe_error_summary(exc))
        return 1
    logger.info("Selesai: %d baris di-upsert ke areas.", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
