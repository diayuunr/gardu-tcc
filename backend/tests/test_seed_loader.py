import re

import pytest

from app.scripts import seed_loader
from app.scripts.seed_loader import RESEARCH_BATCH, SEED_INCIDENTS

_URL_PATTERN = re.compile(r"https?://\S+")

# Kata/pola yang menandakan identitas KORBAN (nama, inisial, usia, status siswa) DAN nama
# sekolah/kampus (keputusan tim: tidak ada nama sekolah di lokasi, REQ-F-042). URL sumber
# dikecualikan dari pemindaian karena disimpan apa adanya.
_VICTIM_IDENTITY_PATTERNS = [
    r"\busia\b", r"\binisial\b", r"\bberinisial\b", r"\b\d{1,2}\s*(tahun|thn)\b",
    r"\bmahasiswa\b", r"\bmahasiswi\b", r"\bpelajar\b", r"\bsiswa\b", r"\bsiswi\b", r"\bsantri\b",
    r"\bkorban (bernama|atas nama)\b", r"\bnama korban\b",
    r"\bsma\b", r"\bsmp\b", r"\bsmk\b", r"\bsekolah\b", r"\bkampus\b", r"\buniversitas\b", r"\bdepan\b",
]

OLD_KEPT = {
    "Jalan Miliran, Umbulharjo, Yogyakarta",
    "Jalan Kabupaten, Trihanggo, Gamping, Sleman, Yogyakarta",
    "Demak Ijo, Sleman, Yogyakarta",
}
UPDATED = {
    "Gedongkuning, Kotagede, Yogyakarta": "Jalan Gedongkuning, perbatasan Kabupaten Bantul dan Kota Yogyakarta",
    "Bumijo, Jetis, Yogyakarta": "Jalan Tentara Rakyat Mataram, Kelurahan Bumijo, Kemantren Jetis, Kota Yogyakarta",
}
# Lokasi yang nama sekolahnya dihapus (teks lama -> teks baru); baris lama harus diperbarui di tempat.
SCHOOL_CLEANED = {
    "Jalan Yos Sudarso, Kotabaru, Kemantren Gondokusuman, depan SMA 3 Yogyakarta":
        "Jalan Yos Sudarso, Kotabaru, Kemantren Gondokusuman",
    "Jalan Ki Mangunsarkoro, depan SMP Muhammadiyah 4 Yogyakarta, Kemantren Pakualaman":
        "Jalan Ki Mangunsarkoro, Kemantren Pakualaman",
}


def _text_without_urls(value: str) -> str:
    return _URL_PATTERN.sub("", value)


# ------------------------------------------------------------------ integritas data


def test_seed_set_has_19_unique_entries_with_unique_times_and_a_source_each():
    assert len(SEED_INCIDENTS) == 19  # 3 lama tidak diubah + 2 diperbarui + 14 baru
    locations = [seed["location_text"] for seed in SEED_INCIDENTS]
    times = [seed["incident_time"] for seed in SEED_INCIDENTS]
    assert len(set(locations)) == 19
    assert len(set(times)) == 19  # tidak ada tanggal/jam identik antar entri
    assert all(seed["sumber"].strip() for seed in SEED_INCIDENTS)  # constraint DB: sumber wajib untuk seed

    batch = [seed for seed in SEED_INCIDENTS if seed.get("batch") == RESEARCH_BATCH]
    assert len(batch) == 16  # 2 diperbarui + 14 baru
    assert all(_URL_PATTERN.search(seed["sumber"]) for seed in batch)  # URL sumber tersimpan


def test_uncertain_times_are_flagged_explicitly_in_the_source_column_and_all_differ():
    uncertain = [seed for seed in SEED_INCIDENTS if seed.get("perkiraan_waktu")]
    assert len(uncertain) == 7  # Gedongkuning, Kotabaru, Caturharjo, Terban, Canden, Cokroaminoto, Giwangan
    for seed in uncertain:
        assert "[PERKIRAAN]" in seed["sumber"] and "BUKAN konfirmasi pasti" in seed["sumber"]
    assert len({seed["incident_time"] for seed in uncertain}) == len(uncertain)

    exact = [seed for seed in SEED_INCIDENTS if seed.get("batch") == RESEARCH_BATCH and not seed.get("perkiraan_waktu")]
    assert all("[PERKIRAAN]" not in seed["sumber"] for seed in exact)  # penanda hanya untuk yang memang perkiraan


def test_research_entries_contain_no_victim_identity_outside_the_given_urls():
    for seed in SEED_INCIDENTS:
        if seed.get("batch") != RESEARCH_BATCH:
            continue  # 3 entri lama tidak diubah dan di luar cakupan aturan batch ini
        scanned = " | ".join(
            [seed["location_text"], seed["incident_type"], _text_without_urls(seed["sumber"])]
        ).lower()
        for pattern in _VICTIM_IDENTITY_PATTERNS:
            assert not re.search(pattern, scanned), f"{pattern!r} ditemukan pada: {seed['location_text']}"


def test_updated_entries_keep_the_link_to_their_old_row_and_kept_entries_are_untouched():
    by_new_location = {seed["location_text"]: seed for seed in SEED_INCIDENTS}
    for old_text, new_text in UPDATED.items():
        assert by_new_location[new_text]["replaces_location_text"] == old_text
    assert OLD_KEPT <= set(by_new_location)
    assert all("replaces_location_text" not in by_new_location[text] for text in OLD_KEPT)
    # Teks lama yang digantikan tidak boleh muncul lagi sebagai entri terpisah (akan jadi duplikat).
    assert not (set(UPDATED) & set(by_new_location))
    for old_text, new_text in SCHOOL_CLEANED.items():
        assert by_new_location[new_text]["replaces_location_text"] == old_text
        assert old_text not in by_new_location  # teks berisi nama sekolah tidak boleh jadi entri
    assert len(SCHOOL_CLEANED) == 2


# ------------------------------------------------------------------ perilaku loader


class _FakeSupabase:
    """Supabase palsu in-memory untuk tabel `incidents`: select/eq/limit, insert, update.eq."""

    def __init__(self, rows):
        self.rows = rows
        self._next_id = 1000

    def table(self, name):
        assert name == "incidents"
        return _Query(self)


class _Query:
    def __init__(self, db):
        self._db, self._filters, self._op, self._payload = db, [], "select", None

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def limit(self, _count):
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def execute(self):
        matched = [r for r in self._db.rows if all(r.get(k) == v for k, v in self._filters)]
        if self._op == "select":
            return type("Resp", (), {"data": matched})()
        if self._op == "insert":
            self._db._next_id += 1
            self._db.rows.append({"id": f"new-{self._db._next_id}", **self._payload})
        else:
            for row in matched:
                row.update(self._payload)
        return type("Resp", (), {"data": []})()


def _existing_rows():
    """Kondisi DB sebelum update: 5 seed lama + 1 insiden komunitas (bukan seed)."""
    old = [
        ("miliran-id", "Jalan Miliran, Umbulharjo, Yogyakarta"),
        ("trihanggo-id", "Jalan Kabupaten, Trihanggo, Gamping, Sleman, Yogyakarta"),
        ("demak-id", "Demak Ijo, Sleman, Yogyakarta"),
        ("gedongkuning-id", "Gedongkuning, Kotagede, Yogyakarta"),
        ("bumijo-id", "Bumijo, Jetis, Yogyakarta"),
    ]
    rows = [{"id": row_id, "location_text": text, "is_seed_data": True} for row_id, text in old]
    rows.append({"id": "komunitas-id", "location_text": "Dekat JEC Jogja", "is_seed_data": False})
    return rows


@pytest.fixture
def loader_env(monkeypatch):
    fake = _FakeSupabase(_existing_rows())
    queries: list[str] = []

    def fake_geocode(query):
        queries.append(query)
        return (-7.0 - len(queries) / 1000, 110.0 + len(queries) / 1000)  # titik unik & deterministik

    monkeypatch.setattr(seed_loader, "get_supabase", lambda: fake)
    monkeypatch.setattr(seed_loader, "geocode_location", fake_geocode)
    return fake, queries


def _seed_rows(fake):
    return [r for r in fake.rows if r["is_seed_data"]]


def test_loader_updates_the_two_old_rows_in_place_and_inserts_only_14_new(loader_env):
    fake, queries = loader_env

    inserted, updated = seed_loader.load_seed_incidents()

    assert (inserted, updated) == (14, 5)  # 5 baris lama diperbarui (3 nilai sama), 14 baru
    seeds = _seed_rows(fake)
    assert len(seeds) == 19
    by_id = {row["id"]: row for row in seeds}
    # Baris LAMA dipertahankan (id sama), hanya isinya yang diperbarui — bukan baris duplikat.
    assert by_id["gedongkuning-id"]["location_text"] == UPDATED["Gedongkuning, Kotagede, Yogyakarta"]
    assert by_id["gedongkuning-id"]["incident_type"] == "Penyerangan dengan gir, korban tewas"
    assert by_id["gedongkuning-id"]["incident_time"] == "2022-04-03T02:30:00+07:00"
    assert by_id["bumijo-id"]["location_text"] == UPDATED["Bumijo, Jetis, Yogyakarta"]
    assert by_id["bumijo-id"]["incident_type"] == "Korban luka-luka"
    assert by_id["bumijo-id"]["incident_time"] == "2023-03-24T05:20:00+07:00"
    assert not any(r["location_text"] in UPDATED for r in seeds)  # teks lama tidak tersisa
    assert [r["id"] for r in fake.rows if not r["is_seed_data"]] == ["komunitas-id"]  # insiden komunitas utuh
    # Gedongkuning memakai query geocoding khusus (teks lengkap akan meleset ke pusat kota Bantul).
    assert "Gedongkuning, Kotagede, Yogyakarta" in queries
    assert "Jalan Gedongkuning, perbatasan Kabupaten Bantul dan Kota Yogyakarta" not in queries


def test_school_names_are_removed_from_location_and_existing_rows_are_updated_in_place(loader_env):
    fake, _ = loader_env
    for index, old_text in enumerate(SCHOOL_CLEANED):  # baris yang sudah ada di DB dengan nama sekolah
        fake.rows.append({"id": f"sekolah-{index}", "location_text": old_text, "is_seed_data": True})

    inserted, updated = seed_loader.load_seed_incidents()

    assert (inserted, updated) == (12, 7)  # 7 baris lama (5 + 2 bernama sekolah) diperbarui, 12 baru
    seeds = _seed_rows(fake)
    assert len(seeds) == 19  # tidak ada duplikat
    by_id = {row["id"]: row for row in seeds}
    for index, new_text in enumerate(SCHOOL_CLEANED.values()):
        assert by_id[f"sekolah-{index}"]["location_text"] == new_text  # id sama, teks baru
    assert not any(re.search(r"\b(sma|smp|depan)\b", r["location_text"].lower()) for r in seeds)


def test_running_the_loader_twice_is_idempotent(loader_env):
    fake, _ = loader_env

    seed_loader.load_seed_incidents()
    inserted, updated = seed_loader.load_seed_incidents()

    assert (inserted, updated) == (0, 19)  # run kedua: tidak ada baris baru
    assert len(_seed_rows(fake)) == 19


def test_geocode_failure_skips_only_that_entry_and_never_inserts_a_row_without_coordinates(loader_env, monkeypatch):
    fake, _ = loader_env
    failing = "Pasar Giwangan, Kecamatan Umbulharjo, Kota Yogyakarta"
    monkeypatch.setattr(
        seed_loader, "geocode_location", lambda query: None if query == failing else (-7.8, 110.4)
    )

    inserted, updated = seed_loader.load_seed_incidents()

    assert (inserted, updated) == (13, 5)  # 14 baru - 1 gagal
    assert failing not in {row["location_text"] for row in fake.rows}
    assert all(row.get("latitude") is not None for row in _seed_rows(fake) if "latitude" in row)
