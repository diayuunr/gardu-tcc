"""Seed loader untuk data awal `incidents` (REQ-F-021: Seed Data Ingestion).

Memuat kejadian klitih yang terdokumentasi di pemberitaan (REQ-F-024: setiap
entri wajib mencatat `sumber`) sebagai titik awal Risk Prediction Agent
sebelum data komunitas cukup banyak (REQ-F-020/023).

ATURAN DATA (berlaku untuk semua entri riset, lihat `batch`):
- Tidak ada nama, inisial, usia spesifik, atau identitas sekolah/kampus KORBAN
  di kolom mana pun — hanya jenis kejadian yang umum (REQ-NF-121/REQ-F-042).
- URL sumber yang diberikan disimpan APA ADANYA di kolom `sumber` (kolom
  `source_url` tidak ada di skema; tidak ada migrasi baru).

PENTING soal presisi tanggal/jam: tidak semua sumber menyebut tanggal atau jam
pasti. Untuk entri seperti itu `incident_time` memakai nilai PLACEHOLDER
(perkiraan), dan kolom `sumber`-nya WAJIB mencatat eksplisit bahwa tanggal/jam
adalah perkiraan, bukan konfirmasi pasti (ditandai `perkiraan_waktu=True` dan
teks "[PERKIRAAN]"). Aturan pengisian placeholder:
- Tanggal sebagian diketahui (mis. hanya jam yang tidak pasti): pakai tanggal
  dari sumber, jam perkiraan yang wajar (pola jam rawan klitih versi JPW).
- Tanggal sama sekali tidak diketahui / tahun tidak pasti: pakai tahun di
  tengah rentang data seed (2022) supaya tidak menambah atau mengurangi bobot
  "terkini" secara sepihak; tanggal & jam sengaja DIVARIASIKAN antar entri.
Placeholder mempengaruhi bucket jam & bobot recency di skor risiko, jadi harus
diganti begitu tanggal aslinya dikonfirmasi. Ini konsisten dengan status seed
data sebagai simulasi (lihat Assumptions di SRS), bukan klaim data resmi
kepolisian.

Kunci opsional per entri:
- `replaces_location_text`: teks lokasi LAMA dari baris yang sama. Dipakai saat
  `location_text` sebuah insiden diperbarui, supaya baris lama ikut diperbarui
  (bukan disisipkan baris baru/duplikat).
- `geocode_query`: teks khusus untuk geocoding bila teks lokasi lengkap
  ter-geocode ke tempat yang salah (mis. "perbatasan Kabupaten Bantul dan Kota
  Yogyakarta" di-geocode ke pusat kota Bantul). `location_text` tetap disimpan apa adanya.
- `batch`, `perkiraan_waktu`: metadata untuk test integritas, TIDAK disimpan ke DB.

Koordinat SENGAJA tidak ditulis manual — diambil lewat `geocode_location()`
yang sama persis dipakai endpoint POST /reports, supaya cara pemrosesan
lokasi konsisten antara seed data dan laporan warga. Presisinya tingkat
kelurahan/POI hasil Mapbox (bisa meleset satu sel grid ~1 km). Kalau satu
lokasi gagal di-geocode, skrip ini melaporkan itu dengan jelas dan TIDAK
menyisipkan baris dengan koordinat kosong untuk seed data (beda dengan
laporan warga, yang tetap disimpan meski koordinat NULL) — seed data yang
sengaja dikurasi tim seharusnya selalu berhasil dipetakan; kalau gagal,
lebih baik ditinjau manual dulu daripada diam-diam masuk tanpa titik peta.

Jalankan dari folder backend/, dengan .env terisi SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, dan MAPBOX_TOKEN:

    python -m app.scripts.seed_loader
"""

import logging
import sys

from app.core.geocoding import geocode_location
from app.core.supabase_client import get_supabase

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
# httpx/httpcore log tiap request di level INFO, termasuk full URL (query
# string berisi access_token). Redam ke WARNING supaya token tidak ikut
# tercetak di terminal/log file, walau token Mapbox "pk." memang publik.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

RESEARCH_BATCH = "riset-farsya"

_PERKIRAAN = "[PERKIRAAN]"

SEED_INCIDENTS = [
    # --- Entri lama yang TIDAK diubah ---------------------------------------
    {
        "location_text": "Jalan Miliran, Umbulharjo, Yogyakarta",
        # Hanya tahun yang diketahui dari sumber -> tanggal/jam placeholder,
        # jam dipilih di rentang 21:00-02:00 WIB (pola jam rawan versi JPW).
        "incident_time": "2020-06-14T21:40:00+07:00",
        "incident_type": "Klitih (korban pelajar SMP)",
        "sumber": "NU Online, pemberitaan korban pelajar SMP di dekat Makam Gajah (2020)",
    },
    {
        "location_text": "Jalan Kabupaten, Trihanggo, Gamping, Sleman, Yogyakarta",
        "incident_time": "2020-09-09T00:55:00+07:00",
        "incident_type": "Klitih (dua kejadian beruntun)",
        "sumber": "Pemberitaan 2020, dua kejadian klitih beruntun di lokasi yang sama",
    },
    {
        "location_text": "Demak Ijo, Sleman, Yogyakarta",
        "incident_time": "2023-10-19T21:55:00+07:00",
        "incident_type": "Bentrok antar kelompok",
        "sumber": "Pemberitaan 2023, titik awal bentrok antar kelompok",
    },
    # --- Entri lama yang DIPERBARUI (insiden sama, jangan insert baru) ------
    {
        "replaces_location_text": "Gedongkuning, Kotagede, Yogyakarta",
        "location_text": "Jalan Gedongkuning, perbatasan Kabupaten Bantul dan Kota Yogyakarta",
        # Teks lengkap di-geocode ke pusat kota Bantul (~8 km meleset); query lama
        # menghasilkan titik yang sama dengan baris sebelumnya.
        "geocode_query": "Gedongkuning, Kotagede, Yogyakarta",
        "incident_time": "2022-04-03T02:30:00+07:00",
        "incident_type": "Penyerangan dengan gir, korban tewas",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Detik.com (Jateng) — https://www.detik.com/jateng/hukum-dan-kriminal/d-6016175/"
            "melihat-lebih-dekat-tkp-klithih-di-jogja-yang-tewaskan-anak-anggota-dprd. "
            f"{_PERKIRAAN} Tanggal 3 April 2022 dari sumber; jam kejadian (dini hari) tidak pasti — "
            "02:30 WIB adalah perkiraan, BUKAN konfirmasi pasti."
        ),
    },
    {
        "replaces_location_text": "Bumijo, Jetis, Yogyakarta",
        "location_text": "Jalan Tentara Rakyat Mataram, Kelurahan Bumijo, Kemantren Jetis, Kota Yogyakarta",
        "incident_time": "2023-03-24T05:20:00+07:00",
        "incident_type": "Korban luka-luka",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Okezone — https://news.okezone.com/read/2023/03/24/510/2786735/"
            "klitih-terjadi-saat-ramadhan-di-yogyakarta-korban-seorang-pelajar"
        ),
    },
    # --- Entri baru ----------------------------------------------------------
    {
        "location_text": "Jalan Ngeksigondo, Kecamatan Kotagede, Kota Yogyakarta",
        "incident_time": "2021-04-14T06:15:00+07:00",
        "incident_type": "Korban penganiayaan dan pelemparan batu",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Sorot Jogja — https://jogja.sorot.co/berita/"
            "mediasi-gagal-keluarga-korban-pelemparan-batu-minta-kasus-dilanjutkan-50144"
        ),
    },
    {
        "location_text": "Jalan Menur, Jopaitan, Palbapang, Bantul",
        "incident_time": "2025-08-17T02:30:00+07:00",
        "incident_type": "Pengeroyokan dengan senjata tajam, 2 korban luka",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Detik.com (Jogja) — https://www.detik.com/jogja/berita/d-8067681/"
            "klitih-di-palbapang-bantul-korban-dan-pelaku-disebut-saling-kenal"
        ),
    },
    {
        "location_text": "Jalan Seyegan - Godean, wilayah Margoluwih",
        "incident_time": "2026-03-25T01:00:00+07:00",
        "incident_type": "Pelemparan batu",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Indozone Jogja — https://jogja.indozone.id/news/2486696388/"
            "aksi-klitih-maut-di-seyegan-sleman-polisi-amankan-dua-orang"
        ),
    },
    {
        "location_text": "Jalan Noto Sukoharjo, Kecamatan Ngaglik, Kabupaten Sleman",
        "incident_time": "2026-03-29T00:30:00+07:00",
        "incident_type": "Penyabetan dengan gesper",
        "batch": RESEARCH_BATCH,
        "sumber": "Instagram (unggahan media sosial) — https://www.instagram.com/reel/DWccm-6k6Cb/",
    },
    {
        # Nama sekolah SENGAJA tidak dicantumkan di lokasi (keputusan tim: kejadian fatal yang
        # dikaitkan dengan nama sekolah bisa terbaca mengidentifikasi/menstigma sekolah, REQ-F-042).
        # `replaces_location_text` = teks lama, supaya baris yang sudah ada diperbarui di tempat.
        "replaces_location_text": (
            "Jalan Yos Sudarso, Kotabaru, Kemantren Gondokusuman, depan SMA 3 Yogyakarta"
        ),
        "location_text": "Jalan Yos Sudarso, Kotabaru, Kemantren Gondokusuman",
        # Sumber tidak menyebut tanggal sama sekali -> placeholder tengah rentang seed.
        "incident_time": "2022-11-12T22:45:00+07:00",
        "incident_type": "Penyerangan dengan luka tusuk, korban meninggal dunia",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "YouTube — https://youtu.be/1_twKuD1Lgg. "
            f"{_PERKIRAAN} Sumber tidak menyebut tanggal kejadian; tanggal & jam di data ini adalah "
            "placeholder (perkiraan), BUKAN konfirmasi pasti."
        ),
    },
    {
        # Nama sekolah dihapus dari lokasi (alasan sama seperti entri Kotabaru di atas).
        "replaces_location_text": (
            "Jalan Ki Mangunsarkoro, depan SMP Muhammadiyah 4 Yogyakarta, Kemantren Pakualaman"
        ),
        "location_text": "Jalan Ki Mangunsarkoro, Kemantren Pakualaman",
        "incident_time": "2026-03-25T03:30:00+07:00",
        "incident_type": "Pembacokan dengan celurit antar kelompok",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Tribrata News Polda DIY — https://jogja.polri.go.id/yogyakarta/tribrata-news/online/detail/"
            "dipicu-perselisihan-internal-geng--bentrokan-sajam-pecah-di-depan-smp-muhammadiyah-4-pakualaman.html"
        ),
    },
    {
        "location_text": "Jalan Godean KM 9, Dusun Senuko, Sidoagung, Godean",
        "incident_time": "2026-04-05T03:00:00+07:00",
        "incident_type": "Penyerangan dengan celurit dan sabit",
        "batch": RESEARCH_BATCH,
        "sumber": "Instagram (unggahan media sosial) — https://www.instagram.com/reel/DX_YyvAE-B7/",
    },
    {
        "location_text": "Dusun Malang, Kalurahan Caturharjo, Kapanewon Sleman",
        # 22 Oktober 2024 = tanggal artikel, bukan tanggal kejadian; jam placeholder.
        "incident_time": "2024-10-22T01:20:00+07:00",
        "incident_type": "Penyerangan dengan gesper",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Batamtimes.co — https://www.batamtimes.co/2024/10/22/"
            "ditangkap-polisi-ini-8-identitas-pelaku-klitih-di-caturharjo-sleman/. "
            f"{_PERKIRAAN} 22 Oktober 2024 adalah tanggal artikel, bukan konfirmasi tanggal kejadian; "
            "tanggal & jam di data ini adalah perkiraan, BUKAN konfirmasi pasti."
        ),
    },
    {
        "location_text": "Dusun Ngabean, Triharjo, Pandak, Bantul",
        "incident_time": "2026-01-03T03:30:00+07:00",
        "incident_type": "Luka bacok akibat sabetan celurit",
        "batch": RESEARCH_BATCH,
        "sumber": "Inilahjogja.com — https://inilahjogja.com/remaja-di-bantul-dibacok-orang-tak-dikenal/",
    },
    {
        "location_text": "Sekitar Jalan C. Simanjuntak, Kelurahan Terban, Kecamatan Gondokusuman",
        "incident_time": "2018-06-07T03:30:00+07:00",
        "incident_type": "Penyerangan dengan celurit, korban tewas",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Tirto.id — https://tirto.id/di-jogja-yang-rawan-klitih-polisi-mesti-kawal-kegiatan-sotr-g8Ue. "
            f"{_PERKIRAAN} Tanggal 7 Juni 2018 dari sumber; jam (saat SOTR) adalah perkiraan sekitar "
            "03:30 WIB, BUKAN konfirmasi pasti."
        ),
    },
    {
        "location_text": "Dusun Gadungan Kepuh, Kalurahan Canden, Kapanewon Jetis, Bantul",
        # Hanya "8 Februari" yang disebut, tahun tidak pasti -> tahun tengah rentang seed.
        "incident_time": "2022-02-08T02:20:00+07:00",
        "incident_type": "Penyerangan dengan celurit",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Instagram (unggahan media sosial) — https://www.instagram.com/p/DUz0Q4nAW1A/. "
            f"{_PERKIRAAN} Sumber hanya menyebut 8 Februari tanpa tahun; tahun 2022 dan jam di data ini "
            "adalah placeholder (perkiraan), BUKAN konfirmasi pasti."
        ),
    },
    {
        "location_text": "Jalan Samas, Srigading, Sanden, Bantul",
        "incident_time": "2026-04-04T01:30:00+07:00",
        "incident_type": "Penyerangan dengan celurit",
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Detik.com (Jogja) — https://www.detik.com/jogja/berita/d-8429968/"
            "gerombolan-remaja-sabet-mobil-pakai-celurit-di-sanden-bantul"
        ),
    },
    {
        "location_text": "Jalan HOS Cokroaminoto, Tegalrejo, Kota Yogyakarta",
        "incident_time": "2022-08-31T20:00:00+07:00",
        "incident_type": "Penganiayaan kelompok, korban tewas",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Kompas.tv — https://www.kompas.tv/regional/324434/"
            "kronologi-mahasiswa-timor-leste-dianiaya-orang-tak-dikenal-hingga-tewas-di-yogyakarta. "
            f"{_PERKIRAAN} Tanggal 31 Agustus 2022 dari sumber; jam kejadian adalah perkiraan sekitar "
            "20:00 WIB, BUKAN konfirmasi pasti."
        ),
    },
    {
        "location_text": "Pasar Giwangan, Kecamatan Umbulharjo, Kota Yogyakarta",
        # Sumber tidak menyebut tanggal sama sekali -> placeholder tengah rentang seed.
        "incident_time": "2022-07-23T21:30:00+07:00",
        "incident_type": "Kekerasan jalanan",
        "perkiraan_waktu": True,
        "batch": RESEARCH_BATCH,
        "sumber": (
            "Instagram (unggahan media sosial) — https://www.instagram.com/reels/DWkwUhgAAqI/. "
            f"{_PERKIRAAN} Sumber tidak menyebut tanggal kejadian; tanggal & jam di data ini adalah "
            "placeholder (perkiraan), BUKAN konfirmasi pasti."
        ),
    },
]


def _find_existing_seed_id(supabase, seed: dict) -> str | None:
    """Cari id baris seed yang sudah ada untuk entri ini (kalau ada).

    Dipakai supaya seed loader ini UPSERT: aman dijalankan berkali-kali
    (idempotent, tidak menggandakan baris), DAN kalau nilai di SEED_INCIDENTS
    diedit lalu skrip dijalankan ulang, baris lama ikut diperbarui alih-alih
    dilewati begitu saja. Kunci pencocokan `location_text` + `is_seed_data=true`
    (bukan ikut `sumber`), karena kita justru ingin bisa mengubah teks
    `sumber`/waktu suatu lokasi tanpa itu dianggap "entri baru".

    Kalau `location_text` sebuah insiden DIPERBARUI, baris lama tidak akan
    ketemu lewat teks barunya — karena itu dicoba juga `replaces_location_text`
    (teks lama), supaya hasilnya UPDATE baris yang sama, bukan baris duplikat.
    """
    candidates = [seed["location_text"]]
    if seed.get("replaces_location_text"):
        candidates.append(seed["replaces_location_text"])

    for candidate in candidates:
        response = (
            supabase.table("incidents")
            .select("id")
            .eq("location_text", candidate)
            .eq("is_seed_data", True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0]["id"]
    return None


def load_seed_incidents() -> tuple[int, int]:
    """Geocode lalu insert/update seluruh SEED_INCIDENTS.

    Return (jumlah_baris_baru, jumlah_baris_diperbarui).
    """
    supabase = get_supabase()
    inserted = 0
    updated = 0
    failed_locations: list[str] = []

    for seed in SEED_INCIDENTS:
        location_text = seed["location_text"]

        geocoded = geocode_location(seed.get("geocode_query", location_text))
        if geocoded is None:
            logger.warning("GAGAL geocode, seed TIDAK disimpan: %s", location_text)
            failed_locations.append(location_text)
            continue

        latitude, longitude = geocoded
        record = {
            "location_text": location_text,
            "latitude": latitude,
            "longitude": longitude,
            "incident_time": seed["incident_time"],
            "incident_type": seed["incident_type"],
            "is_seed_data": True,
            "sumber": seed["sumber"],
        }

        existing_id = _find_existing_seed_id(supabase, seed)

        try:
            if existing_id:
                supabase.table("incidents").update(record).eq("id", existing_id).execute()
            else:
                supabase.table("incidents").insert(record).execute()
        except Exception:  # noqa: BLE001 - gagal satu entri tidak boleh menghentikan entri lain
            logger.exception("Gagal menyimpan seed incident: %s", location_text)
            failed_locations.append(location_text)
            continue

        if existing_id:
            logger.info("Diperbarui: %s -> (%.5f, %.5f)", location_text, latitude, longitude)
            updated += 1
        else:
            logger.info("Tersimpan: %s -> (%.5f, %.5f)", location_text, latitude, longitude)
            inserted += 1

    if failed_locations:
        logger.warning(
            "Lokasi yang GAGAL di-geocode/disimpan (%d): %s",
            len(failed_locations),
            ", ".join(failed_locations),
        )

    return inserted, updated


if __name__ == "__main__":
    new_count, updated_count = load_seed_incidents()
    logger.info(
        "Selesai. %d seed incident baru, %d diperbarui.", new_count, updated_count
    )
    sys.exit(0)
