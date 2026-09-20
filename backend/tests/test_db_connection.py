"""Test sederhana koneksi Supabase: pastikan seed_data bisa diambil dan tidak kosong."""

from backend.db.queries import get_seed_data


def test_get_seed_data_not_empty():
    rows = get_seed_data()
    print(f"Jumlah baris seed_data yang berhasil diambil: {len(rows)}")
    assert len(rows) > 0, "seed_data kosong — cek apakah seed sudah di-insert ke Supabase"
