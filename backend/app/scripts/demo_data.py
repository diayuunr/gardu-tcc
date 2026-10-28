"""Data DEMO insiden untuk presentasi (Fase F) — HANYA untuk lingkungan demo, bukan produksi.

Membuat ~100 insiden SIMULASI yang menyebar di beberapa kecamatan dan ruas jalan besar (Jalan Kaliurang, Ring Road
Utara/Timur, Jalan Parangtritis, Jalan Magelang, Jalan Solo, Jalan Wonosari), di KELIMA bucket jam (termasuk siang dan
sore yang kosong pada data seed), dengan variasi tingkat rendah/sedang/tinggi, supaya peta kerawanan dan Cek Rute terlihat
hidup. Insiden demo ikut skor kerawanan dan Cek Rute persis seperti insiden asli (berstatus `terverifikasi`), tetapi:

- ditandai pada kolom `sumber`: diawali `[DEMO]` dan menyebut "data simulasi ... BUKAN kejadian nyata";
- `is_seed_data` tetap FALSE: tidak pernah tercampur dengan data seed asli (pemberitaan);
- dapat dihapus total dengan `--purge` (hanya baris ber-tag `[DEMO]` yang bukan seed yang disentuh).

PRIVASI: tidak ada nama, ciri, atau cerita individu — hanya titik jalan, jam, dan kategori jenis kejadian dari kosakata
tetap. Koordinat ruas jalan diambil dari geometri rute Mapbox Directions (titik nyata di badan jalan); koordinat
kecamatan dari berkas data/areas_rows.csv. Waktu kejadian dihitung relatif terhadap HARI INI (WIB) supaya selalu "segar";
menjalankan ulang aman (idempoten): baris demo yang sama diperbarui, baris yang tak lagi ada di daftar dihapus.

Jalankan dari folder backend/ dengan .env terisi SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY:

    python -m app.scripts.demo_data --dry-run          # tampilkan rencana + pratinjau skor, tanpa menulis
    python -m app.scripts.demo_data --confirm-demo     # tulis data demo lalu hitung ulang skor
    python -m app.scripts.demo_data --purge            # hapus SEMUA data demo lalu hitung ulang skor

`--confirm-demo` wajib untuk menulis (pengaman agar tidak terjalankan tak sengaja). Peta/Cek Rute di server yang sedang
berjalan menyegarkan cache-nya dalam <= 60 detik.
"""

import argparse
import logging
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from supabase import Client

from app.agents.risk_agent import (
    ScorableIncident,
    compute_risk_scores,
    recalculate_risk_scores,
    time_bucket_of,
)
from app.core.config import get_settings
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.core.timeutil import WIB, to_wib

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DEMO_TAG = "[DEMO]"
DEMO_NOTE = "data simulasi untuk demonstrasi, BUKAN kejadian nyata"
_BATCH = 100

# Jam (WIB) per bucket — harus tetap di dalam rentang TIME_BUCKET_HOURS di risk_agent (diuji).
BUCKET_HOURS = {
    "dini_hari": (1, 2, 3, 0),
    "pagi": (6, 7, 8, 9),
    "siang": (12, 13, 11, 14),
    "sore": (16, 17, 15),
    "malam": (20, 21, 22, 19, 23),
}
# Kategori jenis kejadian (kosakata tetap, lihat incident_index.CATEGORY_RULES) yang wajar per bucket.
BUCKET_TYPES = {
    "dini_hari": ("klitih", "penyerangan", "bentrok antar kelompok", "klitih"),
    "pagi": ("begal/penodongan", "kejadian mencurigakan"),
    "siang": ("begal/penodongan", "kejadian mencurigakan", "pengrusakan"),
    "sore": ("begal/penodongan", "penyerangan", "kejadian mencurigakan"),
    "malam": ("klitih", "penyerangan", "begal/penodongan", "bentrok antar kelompok"),
}
# Sebaran (utara_m, timur_m) titik-titik dalam satu hotspot: rapat (<= ~50 m) seperti klaster kejadian sebenarnya.
_OFFSETS_M = ((0, 0), (25, 15), (-20, 30), (35, -20), (-30, -25), (10, 45), (-40, 10))
_DAYS_AGO = (3, 8, 14, 21, 30, 38, 47, 58, 70, 85, 100, 118, 135)
_M_PER_DEGREE = 111_320.0


@dataclass(frozen=True)
class Hotspot:
    """Satu titik rawan demo: `count` insiden berdekatan pada satu bucket jam.

    Tingkat sel kira-kira: 1 -> rendah, 2-3 -> sedang, >= 4 -> tinggi; 6+ dalam radius kecil membuat ruas rute
    berisiko tinggi, 4-5 membuatnya waspada (lihat route_analysis)."""

    slug: str
    label: str
    latitude: float
    longitude: float
    bucket: str
    count: int


# ---- ruas jalan besar: titik nyata dari geometri Mapbox Directions (lihat dokstring) -------------------------------
# Catatan nama: Mapbox menamai Ring Road Utara bagian barat "Jalan Siliwangi", Ring Road Timur "Jalan Majapahit",
# dan Jalan Raya Solo (timur Maguwo) "Jalan Majapahit"; label di bawah memakai nama yang dikenal warga.
CORRIDOR_HOTSPOTS: tuple[Hotspot, ...] = (
    Hotspot("kal-1", "Jalan Kaliurang (ruas selatan)", -7.75502, 110.38323, "malam", 3),
    Hotspot("kal-2", "Jalan Kaliurang (ruas Ngaglik)", -7.71104, 110.40880, "malam", 7),
    Hotspot("kal-3", "Jalan Kaliurang (ruas utara)", -7.68065, 110.41865, "pagi", 2),
    Hotspot("rru-1", "Ring Road Utara (barat, Jl. Siliwangi)", -7.75286, 110.38053, "dini_hari", 5),
    Hotspot("rru-2", "Ring Road Utara (tengah)", -7.75829, 110.39651, "dini_hari", 2),
    Hotspot("rru-3", "Ring Road Utara (timur)", -7.76274, 110.41701, "sore", 3),
    Hotspot("rrt-1", "Ring Road Timur (Jl. Majapahit)", -7.80615, 110.40926, "malam", 4),
    Hotspot("rrt-2", "Ring Road Timur (selatan)", -7.83135, 110.40734, "sore", 2),
    Hotspot("par-1", "Jalan Parangtritis (ruas kota)", -7.84745, 110.36001, "dini_hari", 3),
    Hotspot("par-2", "Jalan Parangtritis (ruas Bantul)", -7.94537, 110.32988, "dini_hari", 7),
    Hotspot("par-3", "Jalan Parangtritis (ruas pantai)", -8.01660, 110.32291, "sore", 2),
    Hotspot("mag-1", "Jalan Magelang (ruas selatan)", -7.74865, 110.36229, "pagi", 4),
    Hotspot("mag-2", "Jalan Magelang (ruas tengah)", -7.74054, 110.36274, "siang", 4),
    Hotspot("mag-3", "Jalan Magelang (ruas Sleman)", -7.72816, 110.36312, "malam", 5),
    Hotspot("sol-1", "Jalan Solo (Maguwo)", -7.78339, 110.42811, "sore", 5),
    Hotspot("sol-2", "Jalan Solo (Kalasan)", -7.77272, 110.46663, "pagi", 2),
    Hotspot("won-1", "Jalan Wonosari (ruas Piyungan)", -7.82808, 110.44494, "dini_hari", 3),
    Hotspot("won-2", "Jalan Wonosari (ruas Patuk)", -7.83461, 110.46755, "malam", 5),
)

# ---- kecamatan: titik pusat dari data/areas_rows.csv ---------------------------------------------------------------
DISTRICT_HOTSPOTS: tuple[Hotspot, ...] = (
    Hotspot("kec-gondokusuman", "Kecamatan Gondokusuman, Kota Yogyakarta", -7.78280, 110.38220, "dini_hari", 4),
    Hotspot("kec-depok-malam", "Kecamatan Depok, Sleman", -7.76690, 110.41075, "malam", 4),
    Hotspot("kec-depok-siang", "Kecamatan Depok, Sleman", -7.76690, 110.41075, "siang", 3),
    Hotspot("kec-umbulharjo", "Kecamatan Umbulharjo, Kota Yogyakarta", -7.81940, 110.38110, "sore", 2),
    Hotspot("kec-mantrijeron", "Kecamatan Mantrijeron, Kota Yogyakarta", -7.81894, 110.35910, "dini_hari", 1),
    Hotspot("kec-kotagede", "Kecamatan Kotagede, Kota Yogyakarta", -7.82140, 110.39560, "siang", 2),
    Hotspot("kec-danurejan", "Kecamatan Danurejan, Kota Yogyakarta", -7.79319, 110.37218, "malam", 3),
    Hotspot("kec-mlati", "Kecamatan Mlati, Sleman", -7.73939, 110.34588, "sore", 1),
    Hotspot("kec-gamping", "Kecamatan Gamping, Sleman", -7.79032, 110.32020, "siang", 1),
    Hotspot("kec-godean", "Kecamatan Godean, Sleman", -7.78030, 110.29250, "pagi", 2),
    Hotspot("kec-kalasan", "Kecamatan Kalasan, Sleman", -7.74665, 110.46412, "sore", 3),
    Hotspot("kec-banguntapan", "Kecamatan Banguntapan, Bantul", -7.82939, 110.40755, "pagi", 1),
    Hotspot("kec-sewon", "Kecamatan Sewon, Bantul", -7.85751, 110.35703, "siang", 2),
    Hotspot("kec-kasihan", "Kecamatan Kasihan, Bantul", -7.82888, 110.32444, "sore", 1),
    Hotspot("kec-bantul", "Kecamatan Bantul, Bantul", -7.89543, 110.33296, "malam", 2),
    Hotspot("kec-wates", "Kecamatan Wates, Kulon Progo", -7.89062, 110.13207, "siang", 1),
    Hotspot("kec-wonosari", "Kecamatan Wonosari, Gunungkidul", -7.97760, 110.59077, "pagi", 1),
    Hotspot("kec-sleman", "Kecamatan Sleman, Sleman", -7.69378, 110.34899, "dini_hari", 2),
)

HOTSPOTS = CORRIDOR_HOTSPOTS + DISTRICT_HOTSPOTS


@dataclass(frozen=True)
class DemoIncident:
    sumber: str  # kunci unik sekaligus penanda demo
    location_text: str
    latitude: float
    longitude: float
    incident_time: datetime
    incident_type: str
    bucket: str

    def as_record(self) -> dict:
        return {
            "location_text": self.location_text,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "incident_time": self.incident_time.isoformat(),
            "incident_type": self.incident_type,
            "status": "terverifikasi",  # ikut skor & rute seperti insiden komunitas yang sudah terverifikasi
            "is_seed_data": False,  # JANGAN dicampur dengan seed asli
            "sumber": self.sumber,
        }


def _offset(latitude: float, longitude: float, north_m: float, east_m: float) -> tuple[float, float]:
    return (
        round(latitude + north_m / _M_PER_DEGREE, 5),
        round(longitude + east_m / (_M_PER_DEGREE * math.cos(math.radians(latitude))), 5),
    )


def build_demo_incidents(today: date | None = None) -> list[DemoIncident]:
    """Daftar insiden demo — fungsi murni dan deterministik untuk `today` (bawaan: hari ini WIB)."""
    today = today or datetime.now(WIB).date()
    incidents: list[DemoIncident] = []
    for hotspot in HOTSPOTS:
        hours, types = BUCKET_HOURS[hotspot.bucket], BUCKET_TYPES[hotspot.bucket]
        for n in range(hotspot.count):
            serial = len(incidents)
            north, east = _OFFSETS_M[n % len(_OFFSETS_M)]
            latitude, longitude = _offset(hotspot.latitude, hotspot.longitude, north, east)
            moment = datetime.combine(
                today - timedelta(days=_DAYS_AGO[serial % len(_DAYS_AGO)]),
                time(hours[(serial + n) % len(hours)], (37 * serial + 11) % 60),
                tzinfo=WIB,
            )
            incidents.append(
                DemoIncident(
                    sumber=f"{DEMO_TAG} {hotspot.slug}-{n + 1:02d} — {DEMO_NOTE}",
                    location_text=hotspot.label,
                    latitude=latitude,
                    longitude=longitude,
                    incident_time=moment,
                    incident_type=types[(serial + n) % len(types)],
                    bucket=time_bucket_of(moment),
                )
            )
    return incidents


# ------------------------------------------------------------------ pratinjau skor


def preview_levels(demo: list[DemoIncident], others: list[ScorableIncident]) -> dict[str, Counter]:
    """Jumlah sel per bucket per tingkat bila data demo digabung dengan insiden lain (seed + komunitas)."""
    settings = get_settings()
    scorable = [*others, *(ScorableIncident(d.latitude, d.longitude, d.incident_time) for d in demo)]
    table: dict[str, Counter] = defaultdict(Counter)
    for row in compute_risk_scores(scorable, datetime.now(WIB), settings):
        table[row.time_bucket][row.risk_level] += 1
    return table


def _fetch_non_demo_scorable(supabase: Client) -> list[ScorableIncident]:
    rows: list[ScorableIncident] = []
    start = 0
    while True:
        batch = execute_with_retry(
            supabase.table("incidents")
            .select("latitude,longitude,incident_time,sumber,is_seed_data")
            .or_("is_seed_data.eq.true,status.eq.terverifikasi")
            .order("id")
            .range(start, start + 999)
        ).data or []
        for row in batch:
            if str(row.get("sumber") or "").startswith(DEMO_TAG) and not row.get("is_seed_data"):
                continue
            if row.get("latitude") is None or row.get("longitude") is None:
                continue
            rows.append(
                ScorableIncident(float(row["latitude"]), float(row["longitude"]), to_wib(datetime.fromisoformat(row["incident_time"])))
            )
        if len(batch) < 1000:
            return rows
        start += 1000


# ------------------------------------------------------------------ database


def _existing_demo_rows(supabase: Client) -> dict[str, str]:
    """{sumber: id} semua baris demo. Hanya baris ber-tag [DEMO] yang BUKAN seed."""
    found: dict[str, str] = {}
    start = 0
    while True:
        batch = execute_with_retry(
            supabase.table("incidents")
            .select("id,sumber")
            .like("sumber", f"{DEMO_TAG}%")
            .eq("is_seed_data", False)
            .order("id")
            .range(start, start + 999)
        ).data or []
        found.update({row["sumber"]: row["id"] for row in batch})
        if len(batch) < 1000:
            return found
        start += 1000


@dataclass(frozen=True)
class ApplyResult:
    inserted: int
    updated: int
    removed: int


def apply_demo_data(supabase: Client, incidents: list[DemoIncident]) -> ApplyResult:
    """Upsert (kunci: `sumber`) semua insiden demo; hapus baris demo usang yang tak lagi ada di daftar."""
    existing = _existing_demo_rows(supabase)
    wanted = {i.sumber for i in incidents}
    new_rows = [i.as_record() for i in incidents if i.sumber not in existing]
    updated = 0
    for incident in incidents:
        if incident.sumber in existing:
            execute_with_retry(supabase.table("incidents").update(incident.as_record()).eq("id", existing[incident.sumber]))
            updated += 1
    for start in range(0, len(new_rows), _BATCH):
        execute_with_retry(supabase.table("incidents").insert(new_rows[start : start + _BATCH]))
    stale = [row_id for sumber, row_id in existing.items() if sumber not in wanted]
    for row_id in stale:
        execute_with_retry(supabase.table("incidents").delete().eq("id", row_id).eq("is_seed_data", False))
    return ApplyResult(inserted=len(new_rows), updated=updated, removed=len(stale))


def purge_demo_data(supabase: Client) -> int:
    """Hapus semua baris demo (ber-tag [DEMO] dan bukan seed). Return jumlah yang dihapus."""
    existing = _existing_demo_rows(supabase)
    for row_id in existing.values():
        execute_with_retry(supabase.table("incidents").delete().eq("id", row_id).eq("is_seed_data", False))
    return len(existing)


# ------------------------------------------------------------------ CLI


def _print_plan(incidents: list[DemoIncident], table: dict[str, Counter], with_db: bool) -> None:
    by_bucket = Counter(i.bucket for i in incidents)
    logger.info("Rencana: %d insiden demo di %d titik (hotspot).", len(incidents), len(HOTSPOTS))
    logger.info("Insiden per bucket jam: %s", dict(sorted(by_bucket.items())))
    logger.info("Pratinjau sel skor per bucket (%s):", "demo + seed/komunitas di database" if with_db else "hanya data demo")
    for bucket in BUCKET_HOURS:
        counts = table.get(bucket, Counter())
        logger.info("  %-9s tinggi=%-3d sedang=%-3d rendah=%-3d", bucket, counts["tinggi"], counts["sedang"], counts["rendah"])


def _recalculate() -> None:
    result = recalculate_risk_scores()
    if result.blocked_empty:
        logger.warning("Hasil skor KOSONG: skor lama dipertahankan.")
        return
    logger.info("Skor dihitung ulang: %d baris di-upsert, %d usang dihapus.", result.upserted, result.deleted)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Data demo insiden (HANYA lingkungan demo).")
    parser.add_argument("--dry-run", action="store_true", help="tampilkan rencana & pratinjau skor, tanpa menulis")
    parser.add_argument("--purge", action="store_true", help="hapus SEMUA data demo lalu hitung ulang skor")
    parser.add_argument("--confirm-demo", action="store_true", help="WAJIB untuk menulis: saya paham ini data simulasi")
    parser.add_argument("--no-recalculate", action="store_true", help="jangan hitung ulang skor sesudahnya")
    args = parser.parse_args(argv)
    if args.purge and args.dry_run:
        parser.error("--purge dan --dry-run tidak bisa bersamaan")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        supabase = get_supabase()
        if args.purge:
            removed = purge_demo_data(supabase)
            logger.info("Dihapus: %d insiden demo (data seed dan komunitas tidak disentuh).", removed)
            if not args.no_recalculate:
                _recalculate()
            return 0

        incidents = build_demo_incidents()
        if args.dry_run:
            try:
                others, with_db = _fetch_non_demo_scorable(supabase), True
            except Exception as exc:  # noqa: BLE001 - pratinjau tetap berguna tanpa database
                logger.warning("Insiden database tak terbaca, pratinjau hanya data demo: %s", safe_error_summary(exc))
                others, with_db = [], False
            _print_plan(incidents, preview_levels(incidents, others), with_db)
            logger.info("DRY RUN: tidak ada yang ditulis.")
            return 0

        if not args.confirm_demo:
            logger.error("Menulis data demo butuh --confirm-demo (data SIMULASI, jangan di produksi). Tidak ada yang ditulis.")
            return 2
        result = apply_demo_data(supabase, incidents)
        logger.info("Data demo: %d baru, %d diperbarui, %d usang dihapus.", result.inserted, result.updated, result.removed)
        if not args.no_recalculate:
            _recalculate()
        return 0
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1), tanpa data mentah
        logger.error("Data demo GAGAL: %s", safe_error_summary(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
