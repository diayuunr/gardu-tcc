"""Skenario demo presentasi: lapor -> terverifikasi -> skor naik (Fase F). Dijalankan terhadap backend yang SEDANG BERJALAN.

Skrip ini bertindak seperti klien biasa: mengirim 4 laporan lewat API publik `POST /reports` dengan wilayah berjenjang
(3 laporan tentang kejadian yang sama di satu kelurahan dengan kata-kata berbeda + 1 laporan di tempat lain), menunggu
verifikasi di latar belakang server, mencetak status tiap laporan, lalu membandingkan skor kerawanan sebelum dan sesudah.
Yang diharapkan: ketiga laporan kembar menjadi `terverifikasi` (satu insiden), laporan tunggal tetap `menunggu_verifikasi`,
dan skor area naik.

Semua teks laporan berawalan "[SKENARIO DEMO]" (tanpa nama/ciri siapa pun) sehingga mudah dikenali di panel moderasi dan
bisa dihapus bersih dengan `--cleanup`. Status dibaca langsung dari database (butuh .env), karena API publik sengaja tidak
membuka status per laporan.

    python -m app.scripts.demo_scenario                       # backend di http://localhost:8000
    python -m app.scripts.demo_scenario --base-url https://api.contoh.id --timeout 180
    python -m app.scripts.demo_scenario --cleanup             # hapus laporan skenario + insidennya, hitung ulang skor

Batas laporan per IP (RATE_LIMIT_MAX_REQUESTS, bawaan 5 per 10 menit) berlaku: skenario ini memakai 4, jadi jalankan
sekali per 10 menit (atau naikkan batasnya di .env saat latihan). Butuh GEMINI_API_KEY di server agar verifikasi berjalan.
"""

import argparse
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from supabase import Client

from app.agents.risk_agent import recalculate_risk_scores
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.core.timeutil import WIB

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

SCENARIO_TAG = "[SKENARIO DEMO]"
PENDING = "menunggu_verifikasi"
VERIFIED = "terverifikasi"
DEFAULT_BASE_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")


@dataclass(frozen=True)
class ScenarioReport:
    key: str  # "A1".."A3" = kejadian yang sama; "B1" = kejadian tunggal di tempat lain
    place: str  # "A" | "B"
    minutes_ago: int
    text: str


# Kata-kata sengaja berbeda (bukan salinan) tetapi bermakna sama, supaya masuk klaster yang sama tanpa dianggap duplikat.
# Tidak ada nama, ciri fisik, atau plat nomor siapa pun.
SCENARIO: tuple[ScenarioReport, ...] = (
    ScenarioReport("A1", "A", 50, f"{SCENARIO_TAG} Sekelompok pengendara motor membawa senjata tajam mengejar dan menyabet pengendara lain di dekat simpang."),
    ScenarioReport("A2", "A", 45, f"{SCENARIO_TAG} Saya melihat beberapa remaja bermotor mengacungkan benda tajam di pertigaan, ada pengendara yang terluka."),
    ScenarioReport("A3", "A", 40, f"{SCENARIO_TAG} Warga sekitar melaporkan kelompok bermotor mengayunkan celurit di jalan, satu orang terjatuh dan ditolong warga."),
    ScenarioReport("B1", "B", 35, f"{SCENARIO_TAG} Terdengar suara teriakan dan kendaraan melaju kencang di jalan kampung, tidak terlihat jelas apa yang terjadi."),
)
# Tempat A (tiga laporan kembar) dan B (laporan tunggal): petunjuk nama untuk mencari kode wilayah lewat GET /areas.
PLACES = {
    "A": {"kabkota": "sleman", "kecamatan": "depok", "kelurahan": "caturtunggal"},
    "B": {"kabkota": "yogyakarta", "kecamatan": "gondokusuman", "kelurahan": None},
}


@dataclass(frozen=True)
class Region:
    kabkota_kode: str
    kecamatan_kode: str
    kelurahan_kode: str | None
    label: str
    latitude: float | None
    longitude: float | None


class ScenarioError(Exception):
    """Skenario tidak dapat dilanjutkan (pesan aman ditampilkan apa adanya)."""


# ------------------------------------------------------------------ wilayah


def _find(areas: list[dict], hint: str | None) -> dict | None:
    if not hint:
        return None
    return next((a for a in areas if hint in a["nama"].casefold()), None)


def resolve_region(client: httpx.Client, hints: dict) -> Region:
    """Cari kode kabupaten/kota -> kecamatan -> kelurahan lewat GET /areas (alur dropdown berjenjang)."""

    def areas(**params: str) -> list[dict]:
        response = client.get("/areas", params=params)
        response.raise_for_status()
        return response.json()["areas"]

    kabkota = _find(areas(tingkat="kabkota"), hints["kabkota"])
    if kabkota is None:
        raise ScenarioError(f"Kabupaten/kota '{hints['kabkota']}' tidak ditemukan di GET /areas (sudah menjalankan load_areas?).")
    kecamatan = _find(areas(tingkat="kecamatan", parent=kabkota["kode"]), hints["kecamatan"])
    if kecamatan is None:
        raise ScenarioError(f"Kecamatan '{hints['kecamatan']}' tidak ditemukan di {kabkota['nama']}.")
    kelurahan = _find(areas(tingkat="kelurahan", parent=kecamatan["kode"]), hints.get("kelurahan"))
    center = kelurahan if kelurahan and kelurahan.get("latitude") is not None else kecamatan
    label = ", ".join(a["nama"] for a in (kelurahan, kecamatan, kabkota) if a)
    return Region(
        kabkota["kode"], kecamatan["kode"], kelurahan["kode"] if kelurahan else None, label,
        center.get("latitude"), center.get("longitude"),
    )


# ------------------------------------------------------------------ status (database)


def read_statuses(supabase: Client, report_ids: list[str]) -> dict[str, dict]:
    """{id laporan: {status, incident_id, incident_status}} — dibaca langsung dari database."""
    reports = execute_with_retry(supabase.table("reports").select("id,status,incident_id").in_("id", report_ids)).data or []
    incident_ids = list({r["incident_id"] for r in reports if r.get("incident_id")})
    incidents = {}
    if incident_ids:
        incidents = {
            r["id"]: r["status"]
            for r in execute_with_retry(supabase.table("incidents").select("id,status").in_("id", incident_ids)).data or []
        }
    return {
        r["id"]: {"status": r["status"], "incident_id": r.get("incident_id"), "incident_status": incidents.get(r.get("incident_id"))}
        for r in reports
    }


# ------------------------------------------------------------------ skenario


def _post_report(client: httpx.Client, scenario: ScenarioReport, region: Region, now: datetime) -> str:
    payload = {
        "description": scenario.text,
        "occurred_at": (now - timedelta(minutes=scenario.minutes_ago)).isoformat(),
        "kabkota_kode": region.kabkota_kode,
        "kecamatan_kode": region.kecamatan_kode,
        **({"kelurahan_kode": region.kelurahan_kode} if region.kelurahan_kode else {}),
    }
    response = client.post("/reports", json=payload)
    if response.status_code == 429:
        raise ScenarioError("Batas laporan per IP tercapai (429). Tunggu ~10 menit atau naikkan RATE_LIMIT_MAX_REQUESTS di .env.")
    if response.status_code != 201:
        raise ScenarioError(f"Laporan {scenario.key} ditolak server (HTTP {response.status_code}): {response.json().get('detail', '')}")
    return response.json()["id"]


def _score(client: httpx.Client, region: Region, at: datetime) -> dict | None:
    if region.latitude is None or region.longitude is None:
        return None
    response = client.get("/risk/score", params={"lat": region.latitude, "lon": region.longitude, "at": at.isoformat()})
    return response.json() if response.status_code == 200 else None


def _format_score(score: dict | None) -> str:
    if not score:
        return "(tidak tersedia)"
    return f"{score['risk_score']:.2f} ({score['risk_level']}, {score['contributing_incident_count']} insiden, {score['label']})"


def run_scenario(
    client: httpx.Client,
    read: Callable[[list[str]], dict[str, dict]],
    *,
    timeout_seconds: float = 150.0,
    poll_seconds: float = 3.0,
    score_wait_seconds: float = 60.0,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    out: Callable[[str], None] = print,
) -> bool:
    """Jalankan skenario; True bila laporan kembar menjadi terverifikasi DAN skor area naik."""
    now = now or datetime.now(WIB)
    health = client.get("/health")
    if health.status_code != 200:
        raise ScenarioError(f"Backend tidak sehat (HTTP {health.status_code}) di {client.base_url}.")
    regions = {place: resolve_region(client, hints) for place, hints in PLACES.items()}
    for place, region in regions.items():
        out(f"Tempat {place}: {region.label}")

    a_time = now - timedelta(minutes=45)
    baseline = _score(client, regions["A"], a_time)
    out(f"\nSkor SEBELUM (tempat A, jam kejadian): {_format_score(baseline)}\n")

    ids: dict[str, str] = {}
    for scenario in SCENARIO:
        ids[scenario.key] = _post_report(client, scenario, regions[scenario.place], now)
        out(f"Terkirim {scenario.key} -> 201 (status awal: {PENDING})")
        sleep(1.0)

    out("\nMenunggu verifikasi di latar belakang (embedding + klaster)...")
    deadline = clock() + timeout_seconds
    last_line = ""
    states: dict[str, dict] = {}
    while True:
        by_id = read(list(ids.values()))
        states = {key: by_id.get(report_id, {"status": "?", "incident_id": None, "incident_status": None}) for key, report_id in ids.items()}
        line = " | ".join(f"{k}: {s['status']}" + (f" [insiden {s['incident_status']}]" if s["incident_status"] else "") for k, s in states.items())
        if line != last_line:
            out(f"  {line}")
            last_line = line
        twins_done = all(states[k]["status"] == VERIFIED for k in ("A1", "A2", "A3"))
        processed = all(s["incident_id"] for s in states.values())
        if twins_done and processed:
            break
        if clock() >= deadline:
            out("  (batas waktu tercapai)")
            break
        sleep(poll_seconds)

    verified = all(states[k]["status"] == VERIFIED for k in ("A1", "A2", "A3"))
    raised = False
    after = None
    if verified:
        out("\nKlaster terverifikasi. Menunggu skor kerawanan dihitung ulang...")
        base_value = baseline["risk_score"] if baseline else 0.0
        end = clock() + score_wait_seconds
        while True:
            after = _score(client, regions["A"], a_time)
            if after and after["risk_score"] > base_value:
                raised = True
                break
            if clock() >= end:
                break
            sleep(poll_seconds)
        out(f"Skor SESUDAH: {_format_score(after)}")

    out("\n== RINGKASAN ==")
    out(f"Laporan kembar A1-A3 terverifikasi : {'YA' if verified else 'BELUM (cek GEMINI_API_KEY server / log)'}")
    out(f"Laporan tunggal B1                 : {states['B1']['status']} (wajar: menunggu korroborasi)")
    out(f"Skor area A naik                   : {'YA' if raised else 'TIDAK TERLIHAT'}"
        + ("" if raised or not verified else " (cache peta 60 dtk? coba lagi sebentar lagi)"))
    out(f"Bersihkan dengan: python -m app.scripts.demo_scenario --cleanup")
    return verified and raised


# ------------------------------------------------------------------ pembersihan


def cleanup_scenario(supabase: Client) -> tuple[int, int]:
    """Hapus laporan ber-tag [SKENARIO DEMO] dan insiden yang jadi kosong karenanya. Return (laporan, insiden)."""
    reports = execute_with_retry(
        supabase.table("reports").select("id,incident_id").like("description", f"{SCENARIO_TAG}%")
    ).data or []
    if not reports:
        return 0, 0
    incident_ids = {r["incident_id"] for r in reports if r.get("incident_id")}
    for report in reports:
        execute_with_retry(supabase.table("reports").delete().eq("id", report["id"]))
    removed = 0
    for incident_id in incident_ids:
        remaining = execute_with_retry(supabase.table("reports").select("id").eq("incident_id", incident_id).limit(1)).data
        if not remaining:  # insiden hanya hidup dari laporan skenario; seed tidak pernah dihapus
            execute_with_retry(supabase.table("incidents").delete().eq("id", incident_id).eq("is_seed_data", False))
            removed += 1
    return len(reports), removed


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skenario demo: lapor -> terverifikasi -> skor naik.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="URL backend (bawaan: env BACKEND_URL atau localhost:8000)")
    parser.add_argument("--timeout", type=float, default=150.0, help="detik menunggu verifikasi")
    parser.add_argument("--cleanup", action="store_true", help="hapus laporan skenario + insidennya lalu hitung ulang skor")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        supabase = get_supabase()
        if args.cleanup:
            reports, incidents = cleanup_scenario(supabase)
            print(f"Dihapus: {reports} laporan skenario, {incidents} insiden.")
            if reports:
                result = recalculate_risk_scores()
                print(f"Skor dihitung ulang: {result.upserted} baris di-upsert, {result.deleted} usang dihapus.")
            return 0
        with httpx.Client(base_url=args.base_url, timeout=20) as client:
            ok = run_scenario(client, lambda ids: read_statuses(supabase, ids), timeout_seconds=args.timeout)
        return 0 if ok else 1
    except ScenarioError as exc:
        print(f"Skenario berhenti: {exc}", file=sys.stderr)
        return 3
    except httpx.HTTPError as exc:
        print(f"Backend tidak terjangkau di {args.base_url}: {safe_error_summary(exc)}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - kegagalan harus terlihat jelas, tanpa data mentah
        print(f"Skenario GAGAL: {safe_error_summary(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
