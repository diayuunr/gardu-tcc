"""Risk Prediction Agent — versi awal (Gardu).

Modul terpisah sesuai CLAUDE.md aturan #3 (jangan digabung dengan Verification
Agent atau Safe Route Advisor). Versi ini murni hitung skor dari seed_data,
belum memakai laporan warga karena Verification Agent belum tersedia, dan
belum memanggil API AI eksternal mana pun.
"""

from backend.db.queries import get_scoring_areas, get_seed_data

MAX_SCORE = 100
SCORE_PER_MATCH = 20  # poin per kasus (nama lama dipertahankan agar import lain tidak rusak)


class RiskAgentError(Exception):
    """Agent tidak bisa menghitung (mis. seed_data belum punya kode wilayah)."""


class UnknownAreaError(RiskAgentError):
    """`area` tidak ada di tabel areas (tingkat kab/kota atau kecamatan)."""


def calculate_risk_score(area: str, time_slot: str) -> dict:
    """Hitung skor risiko untuk `area` + `time_slot` dari seed_data.

    `area` adalah label di kolom areas.area (sama dengan kunci risk_scores). Dari
    label itu diambil kode wilayahnya:
      - kab/kota : jumlah kasus seed yang kabkota_kode-nya itu
      - kecamatan: jumlah kasus seed yang kecamatan_kode-nya itu
    lalu dikali 20 (SCORE_PER_MATCH), maksimal 100. Satu kasus dihitung sekali
    per tingkat, tidak bergantung pada kata yang kebetulan tertulis di alamat.
    Sesuai format response docs/contracts.md (GET /agents/risk).

    TODO(REQ-F-023): ganti formula sederhana ini dengan pengenalan pola
    musiman (mis. tren bulanan/musiman dari waktu kejadian di seed_data),
    bukan sekadar hitung jumlah entri yang cocok.
    """
    area_norm = area.strip().lower()
    wilayah = next(
        (a for a in get_scoring_areas() if (a.get("area") or "").strip().lower() == area_norm),
        None,
    )
    if wilayah is None:
        raise UnknownAreaError(
            f"Area {area!r} tidak dikenal. Pakai nama di kolom areas.area "
            "untuk kab/kota atau kecamatan."
        )

    seed_rows = get_seed_data()
    if not any(row.get("kecamatan_kode") for row in seed_rows):
        raise RiskAgentError(
            "seed_data belum punya kode wilayah. Jalankan migrasi alamat berjenjang dulu."
        )

    kolom = "kabkota_kode" if wilayah["tingkat"] == "kabkota" else "kecamatan_kode"
    slot = time_slot.strip().lower()
    jumlah = sum(
        1
        for row in seed_rows
        if row.get(kolom) == wilayah["kode"] and (row.get("time_period") or "").lower() == slot
    )

    return {
        "area": wilayah["area"],
        "time_slot": time_slot,
        "score": min(jumlah * SCORE_PER_MATCH, MAX_SCORE),
    }