"""Smoke test: panggil tiap endpoint pada backend yang SEDANG BERJALAN dan laporkan OK/GAGAL.

Jalankan dari folder backend/, setelah `uvicorn app.main:app` menyala (dan .env terisi):

    python -m app.scripts.smoke_test                                   # ke http://127.0.0.1:8000
    python -m app.scripts.smoke_test --base-url https://api.contoh.app --origin https://gardu.contoh.app
    python -m app.scripts.smoke_test --write                           # + kirim SATU laporan uji

Yang diperiksa: /health (termasuk koneksi database), dokumentasi /docs, data wilayah (/areas), heatmap,
ringkasan per kecamatan, skor satu titik, label GPS (/geo/reverse), pencarian tempat (/geo/search, memakai
1 panggilan Mapbox), cek rute (1 panggilan Directions; harus selesai dalam batas waktu demo dan memuat
geometri/segmen/alasan), penolakan input salah dengan pesan Indonesia,
404 berbahasa Indonesia, preflight CORS (bila --origin), dan bahwa TIDAK ADA respons yang
membocorkan traceback. Secara bawaan skrip TIDAK menulis data; `--write` mengirim satu laporan
berteks jelas "[SMOKE TEST]" yang tetap tersimpan di database (hapus manual bila perlu).

Exit code 0 = semua OK, 1 = ada yang GAGAL. Skrip hanya memakai HTTP (tanpa kunci Supabase),
dan tidak mencetak isi respons selain ringkasan status.
"""

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

# Titik uji di Yogyakarta (koordinat langsung, jadi tidak bergantung pada geocoding nama tempat).
_ROUTE_BODY = {
    "origin": {"latitude": -7.812995, "longitude": 110.39872},
    "destination": {"latitude": -7.7830, "longitude": 110.3670},
}
_LEAK_MARKERS = ("Traceback (most recent call last)", 'File "', "supabase.co", "access_token=")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed_ms: int


class _Recorder:
    """Pembungkus client yang mencatat setiap isi respons untuk pemeriksaan kebocoran di akhir."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self.bodies: list[tuple[str, str]] = []

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        response = self.client.request(method, path, **kwargs)
        self.bodies.append((f"{method} {path}", response.text))
        return response


def _is_indonesian_error(response: httpx.Response, status_code: int) -> str | None:
    """None bila respons berupa error `status_code` dengan `detail` string; selain itu alasannya."""
    if response.status_code != status_code:
        return f"status {response.status_code}, diharapkan {status_code}"
    try:
        detail = response.json().get("detail")
    except ValueError:
        return "isi respons bukan JSON"
    if not isinstance(detail, str) or not detail:
        return "field detail bukan teks"
    if detail in ("Not Found", "Method Not Allowed", "Internal Server Error", "Field required"):
        return f"pesan masih bahasa Inggris: {detail}"
    return None


def run_smoke(
    client: httpx.Client,
    *,
    origin: str | None = None,
    write: bool = False,
    route_budget_seconds: float = 4.0,
) -> list[CheckResult]:
    api = _Recorder(client)
    results: list[CheckResult] = []

    def check(name: str, fn: Callable[[], str | None]) -> None:
        """`fn` mengembalikan None (OK) atau teks alasan gagal; exception jaringan = GAGAL."""
        started = time.perf_counter()
        try:
            problem = fn()
        except httpx.HTTPError as exc:
            problem = f"tidak bisa terhubung ({type(exc).__name__})"
        elapsed = int((time.perf_counter() - started) * 1000)
        results.append(CheckResult(name, problem is None, problem or "OK", elapsed))

    def health() -> str | None:
        response = api.request("GET", "/health")
        if response.status_code != 200:
            return f"status {response.status_code} (database tidak terjangkau? cek SUPABASE_URL/KEY)"
        return None if response.json().get("database") == "ok" else "database tidak ok"

    def docs() -> str | None:
        page, schema = api.request("GET", "/docs"), api.request("GET", "/openapi.json")
        if page.status_code != 200 or schema.status_code != 200:
            return f"/docs={page.status_code}, /openapi.json={schema.status_code}"
        return None if schema.json().get("paths") else "openapi.json tanpa path"

    def heatmap() -> str | None:
        response = api.request("GET", "/risk/heatmap")
        if response.status_code != 200:
            return f"status {response.status_code}"
        body = response.json()
        if not {"time_bucket", "cells", "updated_at"} <= set(body):
            return "bentuk respons tidak sesuai"
        return None if body["cells"] else "0 sel skor: data belum ada (jalankan app.scripts.recalculate_risk)"

    def heatmap_invalid() -> str | None:
        return _is_indonesian_error(api.request("GET", "/risk/heatmap", params={"time_bucket": "tengah_malam"}), 422)

    def areas() -> str | None:
        response = api.request("GET", "/areas", params={"tingkat": "kabkota"})
        if response.status_code != 200:
            return f"status {response.status_code}"
        return None if response.json().get("count", 0) > 0 else "0 wilayah: data belum ada (jalankan app.scripts.load_areas)"

    def summary() -> str | None:
        response = api.request("GET", "/risk/summary")
        if response.status_code != 200:
            return f"status {response.status_code} (migrasi 20260923000000 sudah dijalankan?)"
        body = response.json()
        if not {"time_bucket", "regions", "unassigned_cell_count", "updated_at"} <= set(body):
            return "bentuk respons tidak sesuai"
        return None if body["regions"] else "0 kecamatan: jalankan app.scripts.recalculate_risk setelah load_areas"

    def reverse() -> str | None:
        response = api.request("GET", "/geo/reverse", params={"lat": -7.7956, "lon": 110.3695})
        if response.status_code != 200:
            return f"status {response.status_code}"
        return None if response.json().get("label") else "label kosong"

    def search() -> str | None:
        response = api.request("GET", "/geo/search", params={"q": "tugu yogyakarta", "limit": 3})
        if response.status_code == 503:
            return "pencarian tempat tidak tersedia (MAPBOX_TOKEN diisi?)"
        if response.status_code != 200:
            return f"status {response.status_code}"
        results = response.json().get("results") or []
        return None if results and {"label", "place_name", "latitude", "longitude"} <= set(results[0]) else "tidak ada hasil"

    def search_invalid() -> str | None:
        return _is_indonesian_error(api.request("GET", "/geo/search", params={"q": "ab"}), 422)

    def score() -> str | None:
        response = api.request("GET", "/risk/score", params={"lat": -7.7956, "lon": 110.3695})
        if response.status_code != 200:
            return f"status {response.status_code}"
        return None if {"risk_score", "risk_level", "has_data"} <= set(response.json()) else "bentuk respons tidak sesuai"

    def score_invalid() -> str | None:
        return _is_indonesian_error(api.request("GET", "/risk/score", params={"lat": 95, "lon": 110}), 422)

    def route() -> str | None:
        started = time.perf_counter()
        response = api.request("POST", "/route/check", json=_ROUTE_BODY)
        elapsed = time.perf_counter() - started
        if response.status_code == 503:
            return "layanan peta tidak tersedia (MAPBOX_TOKEN diisi?)"
        if response.status_code != 200:
            return f"status {response.status_code}"
        body = response.json()
        if not {"risk_level", "summary", "geometry", "segments", "reasons"} <= set(body):
            return "bentuk respons tidak sesuai"
        if body["geometry"].get("type") != "LineString" or len(body["geometry"].get("coordinates", [])) < 2:
            return "geometri rute kosong"
        if elapsed > route_budget_seconds:
            return f"terlalu lambat: {elapsed:.1f} dtk (batas {route_budget_seconds:.0f} dtk)"
        return None

    def route_invalid() -> str | None:
        return _is_indonesian_error(api.request("POST", "/route/check", json={"origin": {}}), 422)

    def report_invalid() -> str | None:
        return _is_indonesian_error(api.request("POST", "/reports", json={}), 422)

    def not_found() -> str | None:
        response = api.request("GET", "/alamat-yang-tidak-ada")
        problem = _is_indonesian_error(response, 404)
        return problem

    def cors() -> str | None:
        response = api.request(
            "OPTIONS",
            "/reports",
            headers={"Origin": origin or "", "Access-Control-Request-Method": "POST"},
        )
        allowed = response.headers.get("access-control-allow-origin")
        return None if allowed == origin else f"origin {origin} tidak diizinkan (CORS_ALLOW_ORIGINS)"

    def write_report() -> str | None:
        occurred = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        response = api.request(
            "POST",
            "/reports",
            json={
                "description": "[SMOKE TEST] Laporan uji otomatis, abaikan. Tidak ada kejadian sebenarnya di lokasi ini.",
                "location_text": "Tugu Yogyakarta",
                "occurred_at": occurred,
            },
        )
        if response.status_code != 201:
            return f"status {response.status_code}"
        return None if response.json().get("status") == "menunggu_verifikasi" else "status awal tidak sesuai"

    check("GET /health (termasuk database)", health)
    check("GET /docs + /openapi.json", docs)
    check("GET /areas (data wilayah)", areas)
    check("GET /risk/heatmap", heatmap)
    check("GET /risk/summary (per kecamatan)", summary)
    check("GET /risk/heatmap input salah -> 422 Indonesia", heatmap_invalid)
    check("GET /geo/reverse (label GPS)", reverse)
    check("GET /geo/search (Mapbox)", search)
    check("GET /geo/search input salah -> 422 Indonesia", search_invalid)
    check("GET /risk/score", score)
    check("GET /risk/score input salah -> 422 Indonesia", score_invalid)
    check(f"POST /route/check (< {route_budget_seconds:.0f} dtk)", route)
    check("POST /route/check input salah -> 422 Indonesia", route_invalid)
    check("POST /reports input salah -> 422 Indonesia (tanpa menulis)", report_invalid)
    check("GET alamat tak dikenal -> 404 Indonesia", not_found)
    if origin:
        check(f"CORS preflight dari {origin}", cors)
    if write:
        check("POST /reports (menulis 1 laporan uji)", write_report)

    def no_leaks() -> str | None:
        for where, body in api.bodies:
            for marker in _LEAK_MARKERS:
                if marker in body:
                    return f"{where} membocorkan '{marker}'"
        return None

    check("Tidak ada kebocoran detail internal di respons", no_leaks)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test seluruh endpoint backend Gardu yang sedang berjalan.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", help="origin frontend untuk menguji preflight CORS")
    parser.add_argument("--write", action="store_true", help="kirim SATU laporan uji ke database")
    parser.add_argument("--timeout", type=float, default=15.0, help="batas waktu per permintaan (detik)")
    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        results = run_smoke(client, origin=args.origin, write=args.write)

    for result in results:
        label = "OK   " if result.ok else "GAGAL"
        print(f"{label} {result.name} ({result.elapsed_ms} ms)" + ("" if result.ok else f" — {result.detail}"))
    failed = [r for r in results if not r.ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} OK" + (f", {len(failed)} GAGAL" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
