"""Safe Route Advisor — versi MVP (Gardu).

Modul terpisah sesuai CLAUDE.md aturan #3 (jangan digabung dengan
Verification Agent atau Risk Prediction Agent).

KETERBATASAN VERSI INI:
- Cek risiko murni berdasarkan substring match nama area (case-insensitive)
  di teks origin/destination, BUKAN geocoding/routing jalur sungguhan
  (belum pakai Mapbox Directions API). Jadi "rute" di sini cuma dua titik
  teks, bukan jalur nyata yang dilewati.
- Bergantung sepenuhnya pada data yang sudah ada di tabel risk_scores
  (diisi Risk Prediction Agent). Kalau belum ada skor untuk time_slot
  tertentu, hasilnya selalu "aman" — bukan berarti benar-benar aman,
  cuma berarti belum ada data.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.db.queries import get_risk_scores_by_time_slot, get_scoring_areas

# Sama dengan legenda peta: Rawan 70+, Waspada 40-69, Aman di bawah 40.
HIGH_RISK_THRESHOLD = 70
MEDIUM_RISK_THRESHOLD = 40

WIB = timezone(timedelta(hours=7))
_RE_KODE = re.compile(r"^\d{2}\.\d{2}(\.\d{2}(\.\d{4})?)?$")

class RouteAdvisorError(Exception):
    """Dilempar kalau input tidak bisa diproses (mis. departure_time bukan
    format tanggal/waktu yang valid)."""


def _time_slot_from_departure(departure_time: str) -> str:
    """Kategorikan departure_time (ISO 8601) ke salah satu dari 5 time_slot,
    pakai heuristik jam yang sama dengan Verification Agent."""
    try:
        dt = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RouteAdvisorError(
            f"departure_time {departure_time!r} bukan format ISO 8601 yang valid"
        ) from exc

    if dt.tzinfo is not None:
        dt = dt.astimezone(WIB)  # tanpa zona waktu dianggap sudah WIB
    hour = dt.hour
    if 0 <= hour < 5:
        return "dini_hari"
    if 5 <= hour < 11:
        return "pagi"
    if 11 <= hour < 15:
        return "siang"
    if 15 <= hour < 18:
        return "sore"
    return "malam"


def _area_in_route(area: str, origin: str, destination: str) -> bool:
    area_norm = (area or "").strip().lower()
    if not area_norm:
        return False
    return area_norm in (origin or "").lower() or area_norm in (destination or "").lower()


def check_route(
    origin: str,
    destination: str,
    departure_time: str,
    origin_kode: Optional[str] = None,
    destination_kode: Optional[str] = None,
) -> dict:
    """Sesuai docs/contracts.md — POST /agents/route-check.

    Response: { "risk_level": "aman" | "waspada" | "berisiko_tinggi",
                "avoid_areas": [str] }

    Kalau origin_kode / destination_kode diisi (kode dari tabel areas), skor tiap
    ujung diambil dari wilayahnya (kelurahan -> kecamatannya) dan yang tertinggi
    menentukan hasil. Kalau tidak diisi, dipakai pencocokan nama area di teks
    origin/destination seperti sebelumnya.
    """
    time_slot = _time_slot_from_departure(departure_time)
    scores = get_risk_scores_by_time_slot(time_slot)
    skor_per_area = {row["area"]: row["score"] for row in scores}

    high_risk_areas = sorted(a for a, s in skor_per_area.items() if s >= HIGH_RISK_THRESHOLD)

    if origin_kode or destination_kode:
        wilayah = {w["kode"]: w for w in get_scoring_areas()}
        skor_ujung = []
        for kode in (origin_kode, destination_kode):
            if not kode:
                continue
            if not _RE_KODE.match(kode):
                raise RouteAdvisorError(f"kode wilayah {kode!r} tidak valid")
            bagian = kode.split(".")
            if len(bagian) == 4:  # kelurahan -> pakai kecamatannya
                kode = ".".join(bagian[:3])
            baris = wilayah.get(kode)
            if baris is None:
                raise RouteAdvisorError(
                    f"kode wilayah {kode!r} tidak ada di daftar kab/kota/kecamatan"
                )
            skor_ujung.append(skor_per_area.get(baris["area"], 0))

        tertinggi = max(skor_ujung)
        if tertinggi >= HIGH_RISK_THRESHOLD:
            risk_level = "berisiko_tinggi"
        elif tertinggi >= MEDIUM_RISK_THRESHOLD:
            risk_level = "waspada"
        else:
            risk_level = "aman"
    else:
        medium_risk_areas = [
            a for a, s in skor_per_area.items() if MEDIUM_RISK_THRESHOLD <= s < HIGH_RISK_THRESHOLD
        ]
        matches_high = any(_area_in_route(a, origin, destination) for a in high_risk_areas)
        matches_medium = any(_area_in_route(a, origin, destination) for a in medium_risk_areas)

        if matches_high:
            risk_level = "berisiko_tinggi"
        elif matches_medium:
            risk_level = "waspada"
        else:
            risk_level = "aman"

    return {
        "risk_level": risk_level,
        "avoid_areas": high_risk_areas,
    }
