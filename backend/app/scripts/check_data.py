"""Pemeriksaan kualitas data (Fase F): ringkasan insiden/skor/laporan dan daftar anomali. BACA-SAJA — tidak mengubah apa pun.

    python -m app.scripts.check_data                 # laporan teks
    python -m app.scripts.check_data --json          # keluaran JSON (mesin)
    python -m app.scripts.check_data --strict        # exit code 2 bila ada peringatan (untuk CI/pra-demo)
    python -m app.scripts.check_data --skip-recalc-compare   # lewati perbandingan skor tersimpan vs hitung ulang

Yang dilaporkan:
- insiden: total, seed / demo (tag `[DEMO]`) / komunitas (baru vs terverifikasi); tanpa koordinat; di luar DIY;
- skor: jumlah sel per bucket jam dan per tingkat, bucket kosong, kesegaran, dan kesesuaiannya dengan insiden sekarang;
- cakupan kecamatan: kecamatan yang punya insiden / sel skor dari seluruh kecamatan;
- laporan: per status, laporan yatim (verifikasi belum tuntas), dan pelanggaran invarian data.

Log hanya memuat angka dan id; tidak pernah isi laporan atau teks lokasi.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from supabase import Client

from app.agents.reprocess import find_unfinished_reports
from app.agents.risk_agent import TIME_BUCKET_HOURS, recalculate_risk_scores
from app.core.areas import AreaDirectory, get_directory_or_none, in_diy
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.scripts.demo_data import DEMO_TAG

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BUCKETS = tuple(name for name, _start, _end in TIME_BUCKET_HOURS)
LEVELS = ("tinggi", "sedang", "rendah")
SCORE_MAX_AGE_DAYS = 7  # skor lebih tua dari ini dianggap usang (cron hitung ulang seharusnya lebih sering)
_PAGE = 1000


@dataclass(frozen=True)
class Finding:
    severity: str  # "peringatan" | "info"
    code: str
    message: str


@dataclass
class DataReport:
    incidents: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    reports: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "peringatan"]

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))


def _fetch_all(supabase: Client, table: str, columns: str) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        batch = execute_with_retry(supabase.table(table).select(columns).order("id").range(start, start + _PAGE - 1)).data or []
        rows += batch
        if len(batch) < _PAGE:
            return rows
        start += _PAGE


def classify_incident(row: dict) -> str:
    if row.get("is_seed_data"):
        return "seed"
    return "demo" if str(row.get("sumber") or "").startswith(DEMO_TAG) else "komunitas"


def _has_point(row: dict) -> bool:
    return row.get("latitude") is not None and row.get("longitude") is not None


def collect(
    supabase: Client,
    *,
    directory: AreaDirectory | None,
    now: datetime | None = None,
    settings: Settings | None = None,
    find_unfinished: Callable[..., list[str]] = find_unfinished_reports,
    recalculate: Callable[..., object] | None = recalculate_risk_scores,
) -> DataReport:
    settings = settings or get_settings()
    now = now or datetime.now(timezone.utc)
    report = DataReport()

    incidents = _fetch_all(supabase, "incidents", "id,latitude,longitude,incident_time,status,is_seed_data,sumber")
    reports = _fetch_all(supabase, "reports", "id,status,incident_id,latitude,longitude")
    scores = _fetch_all(supabase, "risk_scores", "id,area_name,time_bucket,risk_level,place_name,last_calculated_at")

    # ------------------------------------------------------------------ insiden
    by_class: dict[str, list[dict]] = {"seed": [], "demo": [], "komunitas": []}
    for row in incidents:
        by_class[classify_incident(row)].append(row)
    community = by_class["komunitas"]
    report.incidents = {
        "total": len(incidents),
        "seed": len(by_class["seed"]),
        "demo": len(by_class["demo"]),
        "komunitas": len(community),
        "komunitas_baru": sum(r["status"] == "baru" for r in community),
        "komunitas_terverifikasi": sum(r["status"] == "terverifikasi" for r in community),
        "tanpa_koordinat": {k: sum(not _has_point(r) for r in rows) for k, rows in by_class.items()},
        "di_luar_diy": sum(_has_point(r) and not in_diy(float(r["latitude"]), float(r["longitude"])) for r in incidents),
        "seed_perkiraan_waktu": sum("[PERKIRAAN]" in str(r.get("sumber") or "") for r in by_class["seed"]),
    }
    if not incidents:
        report.add("peringatan", "tidak_ada_insiden", "Tabel incidents kosong: jalankan seed_loader (dan demo_data untuk demo).")
    for kind, count in report.incidents["tanpa_koordinat"].items():
        if count:
            report.add("peringatan", f"insiden_{kind}_tanpa_koordinat", f"{count} insiden {kind} tanpa koordinat: tidak ikut skor maupun Cek Rute.")
    if report.incidents["di_luar_diy"]:
        report.add("peringatan", "insiden_di_luar_diy", f"{report.incidents['di_luar_diy']} insiden berkoordinat di luar wilayah DIY.")
    blank_seed = sum(not str(r.get("sumber") or "").strip() for r in by_class["seed"])
    if blank_seed:
        report.add("peringatan", "seed_tanpa_sumber", f"{blank_seed} data seed tanpa sumber (melanggar REQ-F-024).")
    future = sum(
        datetime.fromisoformat(r["incident_time"]).astimezone(timezone.utc) > now + timedelta(minutes=5) for r in incidents
    )
    if future:
        report.add("peringatan", "insiden_di_masa_depan", f"{future} insiden bertanggal di masa depan.")
    if by_class["demo"]:
        report.add("info", "ada_data_demo", f"{len(by_class['demo'])} insiden DEMO ada di database (hapus dengan demo_data --purge sebelum produksi).")

    # ---------------------------------------------------------------------- skor
    per_bucket = {bucket: Counter() for bucket in BUCKETS}
    for row in scores:
        per_bucket.setdefault(row["time_bucket"], Counter())[row["risk_level"]] += 1
    newest = max((datetime.fromisoformat(r["last_calculated_at"]) for r in scores if r.get("last_calculated_at")), default=None)
    report.scores = {
        "sel_total": len(scores),
        "per_bucket": {b: {"total": sum(c.values()), **{lvl: c[lvl] for lvl in LEVELS}} for b, c in per_bucket.items()},
        "tanpa_place_name": sum(not r.get("place_name") for r in scores),
        "dihitung_terakhir": newest.isoformat() if newest else None,
    }
    scorable = len(by_class["seed"]) + len(by_class["demo"]) + report.incidents["komunitas_terverifikasi"]
    if scorable and not scores:
        report.add("peringatan", "skor_kosong", "Ada insiden yang ikut skor tetapi risk_scores kosong: jalankan recalculate_risk.")
    empty = [b for b in BUCKETS if not sum(per_bucket[b].values())]
    if scores and empty:
        report.add("peringatan", "bucket_kosong", f"Bucket tanpa sel skor: {', '.join(empty)} (peta kosong pada jam itu; data demo mengisinya).")
    if report.scores["tanpa_place_name"] and scores:
        report.add("peringatan", "skor_tanpa_nama_wilayah", f"{report.scores['tanpa_place_name']} sel skor tanpa nama wilayah: jalankan load_areas lalu recalculate_risk.")
    if newest is not None and now - newest.astimezone(timezone.utc) > timedelta(days=SCORE_MAX_AGE_DAYS):
        report.add("peringatan", "skor_usang", f"Skor terakhir dihitung {newest.date()} (> {SCORE_MAX_AGE_DAYS} hari): jadwalkan recalculate_risk.")
    if recalculate is not None:
        try:
            fresh = recalculate(persist=False, supabase=supabase)
            expected = {(r.area_name, r.time_bucket) for r in fresh.rows}
            stored = {(r["area_name"], r["time_bucket"]) for r in scores}
            report.scores["sinkron_dengan_insiden"] = expected == stored
            if expected != stored:
                report.add(
                    "peringatan", "skor_tidak_sinkron",
                    f"Skor tersimpan berbeda dari hitungan insiden saat ini ({len(expected - stored)} sel kurang, {len(stored - expected)} sel berlebih): jalankan recalculate_risk.",
                )
        except Exception as exc:  # noqa: BLE001 - perbandingan hanya pelengkap
            report.add("info", "perbandingan_skor_dilewati", f"Perbandingan skor dilewati: {safe_error_summary(exc)}")

    # ------------------------------------------------------------ cakupan kecamatan
    if directory is not None:
        kecamatan = directory.find("kecamatan")
        with_incident = {
            k.kode
            for r in incidents
            if _has_point(r) and (k := directory.nearest_kecamatan(float(r["latitude"]), float(r["longitude"]), settings.risk_place_max_distance_meters))
        }
        with_score = {r["place_name"] for r in scores if r.get("place_name")}
        report.coverage = {
            "kecamatan_total": len(kecamatan),
            "kecamatan_dengan_insiden": len(with_incident),
            "kecamatan_dengan_skor": len(with_score),
        }
    else:
        report.coverage = {"kecamatan_total": None}
        report.add("info", "tanpa_data_wilayah", "Tabel areas kosong/tak terbaca: cakupan kecamatan tidak dihitung (jalankan load_areas).")

    # ------------------------------------------------------------------ laporan
    incident_by_id = {r["id"]: r for r in incidents}
    members: Counter = Counter()
    all_members: Counter = Counter()
    for r in reports:
        if r.get("incident_id"):
            all_members[r["incident_id"]] += 1
            if r["status"] not in ("ditandai_duplikat", "ditandai_hoaks"):
                members[r["incident_id"]] += 1
    cutoff = now - timedelta(minutes=settings.reprocess_min_age_minutes)
    try:
        orphan_ids = find_unfinished(supabase, 1000, cutoff)
    except Exception as exc:  # noqa: BLE001
        orphan_ids = []
        report.add("info", "yatim_dilewati", f"Pencarian laporan yatim dilewati: {safe_error_summary(exc)}")
    dangling = [r["id"] for r in reports if r.get("incident_id") and r["incident_id"] not in incident_by_id]
    flagged_linked = [r["id"] for r in reports if r["status"] in ("ditandai_duplikat", "ditandai_hoaks") and r.get("incident_id")]
    verified_empty = [r["id"] for r in community if r["status"] == "terverifikasi" and members[r["id"]] == 0]
    unpromoted = [r["id"] for r in community if r["status"] == "baru" and members[r["id"]] >= 2]
    no_report = [r["id"] for r in community if all_members[r["id"]] == 0]
    report.reports = {
        "total": len(reports),
        "per_status": dict(Counter(r["status"] for r in reports)),
        "yatim": len(orphan_ids),
        "tanpa_koordinat": sum(not _has_point(r) for r in reports),
        "mengacu_insiden_hilang": len(dangling),
        "ditandai_tapi_punya_insiden": len(flagged_linked),
        "insiden_terverifikasi_tanpa_laporan": len(verified_empty),
        "insiden_belum_dipromosikan": len(unpromoted),
        "insiden_komunitas_tanpa_laporan": len(no_report),
    }
    if orphan_ids:
        report.add("peringatan", "laporan_yatim", f"{len(orphan_ids)} laporan menunggu verifikasi belum tuntas: jalankan reprocess_reports (atau POST /internal/reprocess).")
    if dangling:
        report.add("peringatan", "laporan_mengacu_insiden_hilang", f"{len(dangling)} laporan mengacu ke insiden yang tidak ada.")
    if flagged_linked:
        report.add("peringatan", "laporan_ditandai_punya_insiden", f"{len(flagged_linked)} laporan duplikat/hoaks masih terhubung ke insiden (melanggar invarian).")
    if verified_empty:
        report.add("peringatan", "insiden_terverifikasi_tanpa_laporan", f"{len(verified_empty)} insiden komunitas terverifikasi tanpa laporan independen: ikut skor padahal tak ada buktinya.")
    if unpromoted:
        report.add("peringatan", "insiden_belum_dipromosikan", f"{len(unpromoted)} insiden 'baru' sudah punya >= 2 laporan independen (seharusnya terverifikasi).")
    if no_report:
        report.add("peringatan", "insiden_komunitas_tanpa_laporan", f"{len(no_report)} insiden komunitas tanpa laporan sama sekali.")
    return report


# ------------------------------------------------------------------ tampilan


def render(report: DataReport) -> list[str]:
    i, s, c, r = report.incidents, report.scores, report.coverage, report.reports
    lines = [
        "== INSIDEN ==",
        f"total {i['total']} | seed {i['seed']} | demo {i['demo']} | komunitas {i['komunitas']} "
        f"(baru {i['komunitas_baru']}, terverifikasi {i['komunitas_terverifikasi']})",
        f"tanpa koordinat: {i['tanpa_koordinat']} | di luar DIY: {i['di_luar_diy']} | seed ber-[PERKIRAAN]: {i['seed_perkiraan_waktu']}",
        "== SKOR KERAWANAN ==",
        f"sel total {s['sel_total']} | tanpa nama wilayah {s['tanpa_place_name']} | dihitung terakhir {s['dihitung_terakhir']}",
    ]
    for bucket in BUCKETS:
        row = s["per_bucket"].get(bucket, {"total": 0, "tinggi": 0, "sedang": 0, "rendah": 0})
        lines.append(f"  {bucket:<9} total {row['total']:<4} tinggi {row['tinggi']:<3} sedang {row['sedang']:<3} rendah {row['rendah']}")
    if "sinkron_dengan_insiden" in s:
        lines.append(f"sinkron dengan insiden saat ini: {'ya' if s['sinkron_dengan_insiden'] else 'TIDAK'}")
    lines.append("== CAKUPAN KECAMATAN ==")
    if c.get("kecamatan_total") is not None:
        lines.append(f"{c['kecamatan_dengan_insiden']} dari {c['kecamatan_total']} kecamatan punya insiden; {c['kecamatan_dengan_skor']} punya sel skor")
    else:
        lines.append("(data wilayah tidak tersedia)")
    lines += [
        "== LAPORAN ==",
        f"total {r['total']} | per status {r['per_status']} | yatim {r['yatim']} | tanpa koordinat {r['tanpa_koordinat']}",
        "== TEMUAN ==",
    ]
    lines += [f"[{f.severity.upper()}] {f.message}" for f in report.findings] or ["Tidak ada anomali."]
    return lines


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Periksa kualitas data Gardu (baca-saja).")
    parser.add_argument("--json", action="store_true", help="keluaran JSON")
    parser.add_argument("--strict", action="store_true", help="exit code 2 bila ada peringatan")
    parser.add_argument("--skip-recalc-compare", action="store_true", help="lewati perbandingan skor tersimpan vs hitung ulang")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        supabase = get_supabase()
        report = collect(
            supabase,
            directory=get_directory_or_none(supabase),
            recalculate=None if args.skip_recalc_compare else recalculate_risk_scores,
        )
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas (exit code 1), tanpa data mentah
        print(f"Pemeriksaan data GAGAL: {safe_error_summary(exc)}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=1, default=str))
    else:
        print("\n".join(render(report)))
    return 2 if args.strict and report.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
