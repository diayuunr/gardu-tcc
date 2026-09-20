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

from datetime import datetime

from backend.db.queries import get_risk_scores_by_time_slot

HIGH_RISK_THRESHOLD = 60
MEDIUM_RISK_THRESHOLD = 30


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


def check_route(origin: str, destination: str, departure_time: str) -> dict:
    """Sesuai docs/contracts.md — POST /agents/route-check.

    Response: { "risk_level": "aman" | "waspada" | "berisiko_tinggi",
                "avoid_areas": [str] }
    """
    time_slot = _time_slot_from_departure(departure_time)
    scores = get_risk_scores_by_time_slot(time_slot)

    high_risk_areas = sorted({row["area"] for row in scores if row["score"] > HIGH_RISK_THRESHOLD})
    medium_risk_areas = [
        row["area"]
        for row in scores
        if MEDIUM_RISK_THRESHOLD <= row["score"] <= HIGH_RISK_THRESHOLD
    ]

    matches_high = any(_area_in_route(area, origin, destination) for area in high_risk_areas)
    matches_medium = any(_area_in_route(area, origin, destination) for area in medium_risk_areas)

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
