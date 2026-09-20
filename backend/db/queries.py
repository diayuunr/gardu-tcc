"""Query helper dasar untuk tabel Supabase Gardu.

Skema kolom mengikuti docs/contracts.md — jangan ubah tanpa update kontrak.
"""

from datetime import datetime, timezone
from typing import Optional

from backend.db.supabase_client import supabase


class DBQueryError(Exception):
    """Dilempar saat query ke Supabase gagal, dengan pesan yang jelas."""


# Kolom tabel reports yang boleh diisi dari luar, sesuai docs/contracts.md.
# CLAUDE.md aturan #4: dilarang menyimpan identitas pelapor (nama, no HP,
# akun medsos) — field apa pun di luar daftar ini dibuang, bukan disimpan.
_REPORT_ALLOWED_FIELDS = {
    "description",
    "location",
    "lat",
    "lng",
    "reported_at",
    "status",
    "embedding",  # diisi Verification Agent, bukan endpoint publik
}


def insert_report(data: dict) -> dict:
    """Insert satu baris ke tabel reports. Hanya kolom yang ada di
    docs/contracts.md yang disimpan; field lain (mis. nama, no HP, akun
    medsos) otomatis dibuang, tidak pernah masuk ke database."""
    safe_data = {k: v for k, v in data.items() if k in _REPORT_ALLOWED_FIELDS}

    try:
        response = supabase.table("reports").insert(safe_data).execute()
    except Exception as exc:
        raise DBQueryError(f"Gagal insert ke tabel reports: {exc}") from exc

    if not response.data:
        raise DBQueryError(f"Insert ke tabel reports tidak mengembalikan data: {response}")

    return response.data[0]


def get_report_by_id(report_id: str) -> Optional[dict]:
    """Ambil satu laporan dari tabel reports berdasarkan id.
    Return None kalau id tidak ditemukan."""
    try:
        response = supabase.table("reports").select("*").eq("id", report_id).execute()
    except Exception as exc:
        raise DBQueryError(f"Gagal ambil report id={report_id!r}: {exc}") from exc

    if not response.data:
        return None

    return response.data[0]


def get_recent_reports(since: datetime) -> list:
    """Ambil reports yang dibuat (created_at) sejak `since`. Dipakai oleh
    Verification Agent untuk heuristik clustering — lihat catatan di
    backend/agents/verification.py soal keterbatasannya."""
    try:
        response = (
            supabase.table("reports")
            .select("id, location, reported_at, status, created_at")
            .gte("created_at", since.isoformat())
            .execute()
        )
    except Exception as exc:
        raise DBQueryError(f"Gagal ambil recent reports sejak {since.isoformat()}: {exc}") from exc

    return response.data


def update_report_verification(report_id: str, status: str, location: Optional[str] = None) -> dict:
    """Update hasil verifikasi ke tabel reports.

    CATATAN PENTING: docs/contracts.md untuk tabel `reports` TIDAK
    mendefinisikan kolom `time_period`, `incident_type`, atau `cluster_id`
    (kolom itu cuma ada di response API /agents/verify, bukan di skema
    tabel). Jadi fungsi ini SENGAJA cuma update `location` dan `status` —
    field lain hasil ekstraksi cuma dikembalikan lewat response API, tidak
    dipersist. Kalau perlu disimpan permanen, itu perubahan skema yang wajib
    didiskusikan tim dulu (CLAUDE.md aturan #1-2), bukan ditambahkan diam-diam
    di sini.
    """
    update_fields = {"status": status}
    if location:
        update_fields["location"] = location

    try:
        response = (
            supabase.table("reports")
            .update(update_fields)
            .eq("id", report_id)
            .execute()
        )
    except Exception as exc:
        raise DBQueryError(f"Gagal update verifikasi report id={report_id!r}: {exc}") from exc

    if not response.data:
        raise DBQueryError(f"Update report id={report_id!r} tidak menemukan baris (0 rows affected)")

    return response.data[0]


def get_seed_data() -> list:
    """Ambil semua baris dari tabel seed_data."""
    try:
        response = supabase.table("seed_data").select("*").execute()
    except Exception as exc:
        raise DBQueryError(f"Gagal ambil data dari tabel seed_data: {exc}") from exc

    return response.data


def get_risk_score(area: str, time_slot: str) -> Optional[dict]:
    """Ambil skor risiko untuk satu area + time_slot dari tabel risk_scores.
    Return None kalau belum ada skor untuk kombinasi tersebut."""
    try:
        response = (
            supabase.table("risk_scores")
            .select("*")
            .eq("area", area)
            .eq("time_slot", time_slot)
            .execute()
        )
    except Exception as exc:
        raise DBQueryError(
            f"Gagal ambil risk score untuk area={area!r}, time_slot={time_slot!r}: {exc}"
        ) from exc

    if not response.data:
        return None

    return response.data[0]


def get_risk_scores_by_time_slot(time_slot: str) -> list:
    """Ambil semua baris risk_scores untuk satu time_slot. Dipakai Safe
    Route Advisor untuk cek area berisiko di sepanjang rute."""
    try:
        response = supabase.table("risk_scores").select("*").eq("time_slot", time_slot).execute()
    except Exception as exc:
        raise DBQueryError(f"Gagal ambil risk scores untuk time_slot={time_slot!r}: {exc}") from exc

    return response.data


def upsert_risk_score(area: str, time_slot: str, score: float) -> dict:
    """Simpan/update skor risiko untuk satu area + time_slot di tabel
    risk_scores. Primary key tabel ini adalah (area, time_slot), jadi
    dipanggil ulang untuk area/time_slot yang sama akan meng-update baris
    yang sudah ada, bukan bikin duplikat."""
    row = {
        "area": area,
        "time_slot": time_slot,
        "score": score,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        response = (
            supabase.table("risk_scores")
            .upsert(row, on_conflict="area,time_slot")
            .execute()
        )
    except Exception as exc:
        raise DBQueryError(
            f"Gagal upsert risk score untuk area={area!r}, time_slot={time_slot!r}: {exc}"
        ) from exc

    if not response.data:
        raise DBQueryError(f"Upsert ke tabel risk_scores tidak mengembalikan data: {response}")

    return response.data[0]
