"""Risk Prediction Agent — versi awal (Gardu).

Modul terpisah sesuai CLAUDE.md aturan #3 (jangan digabung dengan Verification
Agent atau Safe Route Advisor). Versi ini murni hitung skor dari seed_data,
belum memakai laporan warga karena Verification Agent belum tersedia, dan
belum memanggil API AI eksternal mana pun.
"""

from backend.db.queries import get_seed_data

MAX_SCORE = 100
SCORE_PER_MATCH = 20


def calculate_risk_score(area: str, time_slot: str) -> dict:
    """Hitung skor risiko sederhana untuk `area` + `time_slot` dari seed_data.

    Formula awal: jumlah entri seed_data yang location-nya mengandung `area`
    DAN time_period-nya cocok dengan `time_slot`, dikali 20, dibatasi maksimal
    100. Sesuai format response docs/contracts.md (GET /agents/risk).

    TODO(REQ-F-023): ganti formula sederhana ini dengan pengenalan pola
    musiman (mis. tren bulanan/musiman dari waktu kejadian di seed_data),
    bukan sekadar hitung jumlah entri yang cocok.
    """
    seed_rows = get_seed_data()

    area_lower = area.strip().lower()
    time_slot_lower = time_slot.strip().lower()

    matched = [
        row
        for row in seed_rows
        if area_lower in (row.get("location") or "").lower()
        and (row.get("time_period") or "").lower() == time_slot_lower
    ]

    score = min(len(matched) * SCORE_PER_MATCH, MAX_SCORE)

    return {
        "area": area,
        "time_slot": time_slot,
        "score": score,
    }
