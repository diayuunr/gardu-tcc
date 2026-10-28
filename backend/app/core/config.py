from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Konfigurasi aplikasi, seluruh nilai wajib diisi lewat .env (tidak ada hardcode)."""

    supabase_url: str
    supabase_service_role_key: str

    # Keputusan final (CLAUDE.md [AI PROVIDER]): SEMUA 3 AI Agent (Verification,
    # Risk Prediction, Safe Route Advisor) memakai Gemini lewat GEMINI_API_KEY.
    # `anthropic_api_key` TIDAK dipakai modul manapun; sengaja dibiarkan sebagai
    # opsi cadangan dan hanya boleh dipakai kalau user memintanya eksplisit.
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    mapbox_token: str | None = None

    # Daftar origin dipisah koma (lihat app/core/cors.py): di-trim, entri kosong diabaikan,
    # "*" DITOLAK karena API memakai allow_credentials.
    cors_allow_origins: str = "http://localhost:3000"

    # Percayai header X-Forwarded-For untuk IP klien (rate limit). Aktifkan HANYA di belakang proxy
    # tepercaya (mis. edge Railway yang menimpa header itu); di lokal biarkan false supaya klien
    # tidak bisa memalsukan IP-nya.
    trust_proxy_headers: bool = False

    # Batas waktu panggilan eksternal (ASUMSI SIMULASI, bisa disetel via env). Tanpa ini klien
    # Supabase menunggu sampai 120 dtk dan request menggantung saat Supabase lambat.
    supabase_timeout_seconds: float = 10.0
    gemini_timeout_seconds: float = 10.0  # ekstraksi jenis kejadian & embedding (proses latar belakang)

    # REQ-NF-122: batasi laporan per IP dalam rentang waktu singkat.
    rate_limit_max_requests: int = 5
    rate_limit_window_seconds: int = 600

    # Data wilayah berjenjang (tabel `areas`). Semua angka = ASUMSI SIMULASI, bisa disetel via env.
    areas_cache_ttl_seconds: int = 600  # data wilayah hampir statis; cache di memori per proses
    # Hasil Mapbox untuk alamat laporan hanya diterima bila jatuh dalam radius ini dari pusat wilayah
    # terpilih (kelurahan, atau kecamatan). Terukur dari data: kelurahan terjauh dari pusat
    # kecamatannya 7,2 km, jadi 8 km cukup longgar tanpa menerima titik di kecamatan lain.
    report_geocode_max_distance_meters: int = 8000
    # Validasi geocode_areas: jarak maksimum titik hasil geocoding ke pusat induknya.
    # Terukur dari data: kelurahan->kecamatan maks 7,2 km; kecamatan->kabupaten maks 28,4 km.
    areas_geocode_max_kelurahan_distance_meters: int = 12000
    areas_geocode_max_kecamatan_distance_meters: int = 40000
    areas_geocode_delay_seconds: float = 0.2  # jeda antar panggilan Mapbox (batas ~600/menit)

    # REQ-F-011/012/013: ambang batas clustering laporan berbasis embedding.
    # similarity di sini cosine similarity (0-1, makin tinggi makin mirip).
    verification_similarity_threshold: float = 0.82  # dianggap kejadian yang sama
    verification_duplicate_threshold: float = 0.95  # dianggap kemiripan teks mencurigakan (kemungkinan duplikat)
    verification_time_window_hours: int = 12  # rentang waktu "berdekatan" di kedua arah
    verification_geo_bbox_degrees: float = 0.02  # ~kurang dari 2.5km di lintang Yogyakarta

    # REQ-F-012: heuristik deterministik penanda laporan tidak wajar (ASUMSI SIMULASI,
    # sengaja konservatif supaya laporan sah tidak salah ditandai).
    verification_hoax_min_distinct_chars: int = 4  # teks dengan huruf/angka berbeda < ini = karakter berulang
    verification_hoax_repeat_min_words: int = 4  # satu kata yang sama diulang >= sekian kali tanpa kata lain

    # REQ-NF-110: skrip pemrosesan ulang laporan yang verifikasinya gagal (ASUMSI SIMULASI).
    # Jeda antar laporan menjaga kuota free tier Gemini (15 request/menit per model).
    reprocess_delay_seconds: float = 4.0
    reprocess_batch_limit: int = 200  # batas laporan per kali jalan skrip
    reprocess_min_age_minutes: int = 10  # hanya laporan yang lebih tua dari ini (hindari balapan dengan background task)

    # Fase E. Daftar laporan publik (/reports/public, /reports/stats) — ASUMSI SIMULASI.
    public_reports_max_page_size: int = 50
    public_reports_default_page_size: int = 20
    public_reports_cache_seconds: int = 5  # cache memori daftar/statistik publik (juga dikosongkan saat laporan masuk/diverifikasi)
    public_reports_rate_limit_max_requests: int = 60
    public_reports_rate_limit_window_seconds: int = 60
    # Panel moderasi: batas per-IP (mencegah tebakan token) dan ukuran halaman.
    moderation_rate_limit_max_requests: int = 120
    moderation_rate_limit_window_seconds: int = 60
    moderation_max_page_size: int = 100
    # Endpoint internal (reprocess/recalculate) dilindungi token rahasia di header X-Internal-Token.
    # KOSONG = endpoint internal nonaktif (menjawab 404). Isi dengan string acak panjang (>= 32 karakter).
    internal_api_token: str = ""
    internal_reprocess_max_batch: int = 20  # batas laporan per panggilan (proses berjalan di latar belakang)
    internal_rate_limit_max_requests: int = 30
    internal_rate_limit_window_seconds: int = 60

    # REQ-F-020/022/023: parameter Risk Prediction Agent. SEMUA nilai di bawah
    # adalah ASUMSI SIMULASI tim (SRS Assumptions #5: seed data = simulasi, bukan
    # klaim data resmi kepolisian) — disetel lewat env, bukan fakta empiris.
    risk_grid_cell_degrees: float = 0.01  # sisi sel area ~1,1 km
    # Nama wilayah sel grid = kecamatan TERDEKAT (jarak pusat sel ke pusat kecamatan), bukan batas
    # poligon resmi. Sel yang lebih jauh dari ini dari kecamatan mana pun tetap berlabel grid netral.
    # Terukur dari data: kelurahan terjauh dari pusat kecamatannya 7,2 km, jadi 8 km cukup longgar.
    risk_place_max_distance_meters: int = 8000
    risk_recency_half_life_days: int = 1825  # kejadian 5 tahun lalu berbobot separuh
    # Makin kecil = skor makin cepat jenuh menuju 10. Dengan 3.0, satu insiden berbobot
    # ~1 menghasilkan skor 2,83 ("rendah"); dua insiden 4,87 ("sedang"); empat 7,36 ("tinggi").
    risk_score_saturation_scale: float = 3.0
    risk_level_medium_threshold: float = 3.0  # skor >= ini -> "sedang"
    risk_level_high_threshold: float = 7.0  # skor >= ini -> "tinggi"
    risk_ramadan_lead_days: int = 14  # jendela "jelang Ramadan" sebelum 1 Ramadan
    risk_ramadan_multiplier: float = 1.3  # pengali jelang + selama Ramadan (REQ-F-023), dipakai saat BACA
    risk_ramadan_dini_hari_multiplier: float = 1.2  # tambahan saat Ramadan di jam sahur/SOTR
    # Pelebaran antar sel: bobot kontribusi insiden di 8 sel tetangga (0 = dimatikan).
    risk_neighbor_weight: float = 0.25
    # Sel tetangga yang TIDAK punya insiden sendiri hanya diberi baris skor bila skornya
    # >= ini, supaya satu insiden tunggal tidak "mengecat" delapan sel di sekitarnya.
    risk_neighbor_min_score: float = 1.0

    # REQ-F-030..032: parameter Safe Route Advisor. SEMUA angka = ASUMSI SIMULASI, disetel lewat env.
    route_check_step_meters: int = 125  # jarak antar titik cek di sepanjang rute (100-150 m)
    route_max_samples: int = 400  # batas titik cek per rute; rute sangat panjang dijarangkan
    # Analisis kedekatan insiden: tiap titik cek menghitung insiden dalam radius ini.
    route_incident_radius_meters: int = 300
    route_incident_kernel: Literal["linear", "gaussian"] = "linear"  # bobot jarak: 1 di titik, 0 di tepi radius
    # Bobot insiden yang jam kejadiannya di bucket BERSEBELAHAN dengan jam tiba (sama = 1.0, lainnya = 0).
    route_incident_adjacent_bucket_weight: float = 0.5
    # "Ada data" di sekitar titik bila ada insiden terskor (jam apa pun) dalam radius ini; dipakai untuk
    # data_coverage, supaya "tidak ada insiden dekat" bisa dibedakan dari "belum ada data sama sekali".
    route_data_coverage_radius_meters: int = 1500
    route_incident_cache_seconds: int = 60  # cache indeks insiden di memori (di-invalidasi saat skor dihitung ulang)
    # Aturan status berbasis panjang paparan (lihat docstring app/agents/route_agent.py).
    route_high_exposure_meters: int = 200  # panjang jalur berskor TINGGI agar rute berisiko_tinggi
    route_medium_exposure_meters: int = 400  # panjang jalur berskor sedang+ agar rute waspada
    # Satu titik dengan skor >= ini membuat rute berisiko_tinggi berapa pun panjang paparannya.
    route_critical_score_threshold: float = 8.5
    # data_limited=true bila cakupan data (titik berdata / titik cek) <= ini.
    # 0.0 = hanya bila TIDAK ADA data sama sekali pada rute.
    route_limited_coverage_threshold: float = 0.0
    route_geometry_tolerance_meters: int = 15  # penjarangan garis (Douglas-Peucker) untuk digambar di peta
    route_max_alternatives: int = 2  # rute alternatif Mapbox yang ikut dinilai (maks)
    # Alternatif hanya disarankan bila levelnya lebih rendah, atau levelnya sama dan skor
    # tertingginya lebih rendah sedikitnya sekian poin (hindari saran karena selisih sepele).
    route_alternative_min_score_gain: float = 0.5
    # ...dan datanya sebanding (cakupan >= rasio ini x cakupan rute utama), dan tidak terlalu lebih lama.
    route_alternative_min_coverage_ratio: float = 0.8
    route_alternative_max_extra_time_ratio: float = 0.5
    # Hasil geocoding teks yang jatuh dalam radius ini dari pusat kota/kabupaten dianggap
    # "pusat wilayah" (Mapbox sering mengembalikan pusat kota untuk nama yang tidak dikenal).
    route_geocode_generic_radius_meters: int = 500
    route_departure_grace_minutes: int = 5  # waktu berangkat lebih lama dari ini di masa lalu ditolak

    # Pencarian tempat (autocomplete): batas per-IP terpisah dan cache singkat (ASUMSI SIMULASI).
    geo_search_rate_limit_max_requests: int = 60
    geo_search_rate_limit_window_seconds: int = 60
    geo_search_cache_seconds: int = 600  # cache LRU hasil pencarian (hanya bila tak ada lapisan yang gagal)
    geo_search_cache_max_entries: int = 512
    # Pencarian tempat BERLAPIS: landmark lokal > Photon (OSM) > nama wilayah (tabel areas) > Mapbox (cadangan).
    geo_photon_enabled: bool = True
    geo_photon_url: str = "https://photon.komoot.io/api/"
    # Server publik Photon (komoot) meminta User-Agent yang jelas dan pemakaian wajar. Isi kontak Anda lewat env.
    geo_photon_user_agent: str = "Gardu/1.0 (aplikasi kesadaran keselamatan jalan Yogyakarta)"
    geo_photon_timeout_seconds: float = 3.0
    # Setelah Photon gagal, lewati selama ini (sirkuit pemutus) supaya tiap pencarian tidak menunggu timeout.
    geo_photon_cooldown_seconds: int = 60
    # Nominatim (OSM) setelah Photon: HANYA untuk penyelesaian teks akhir (asal/tujuan /route/check) dan untuk
    # autocomplete bila Photon sedang gagal. Kebijakan pemakaian publik: maks 1 permintaan/detik dan User-Agent
    # yang jelas dengan kontak (isi lewat env GEO_NOMINATIM_USER_AGENT).
    geo_nominatim_enabled: bool = True
    geo_nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    geo_nominatim_user_agent: str = "Gardu/1.0 (aplikasi kesadaran keselamatan jalan Yogyakarta)"
    geo_nominatim_timeout_seconds: float = 3.0
    geo_nominatim_cache_seconds: int = 1800  # 30 menit
    geo_nominatim_cache_max_entries: int = 256
    geo_nominatim_min_interval_seconds: float = 1.0  # batas laju dalam proses
    geo_nominatim_max_wait_seconds: float = 1.5  # penyelesaian teks akhir boleh menunggu giliran selama ini
    geo_nominatim_cooldown_seconds: int = 60  # dilewati selama ini setelah gagal
    # Mapbox hanya dipanggil bila lapisan sebelumnya menghasilkan kurang dari ini (1 = hanya saat kosong).
    geo_mapbox_fallback_min_results: int = 1
    # Dua hasil dianggap duplikat bila jaraknya < ini DAN namanya mirip.
    geo_dedupe_distance_meters: int = 150
    # Muat direktori wilayah di latar belakang saat server menyala (permintaan pertama ~3 dtk lebih cepat).
    startup_warmup_enabled: bool = True
    # Satu pemeriksaan rute = 2 geocoding + 1 Directions (+ Gemini): batas per-IP terpisah dari laporan.
    route_check_rate_limit_max_requests: int = 20
    route_check_rate_limit_window_seconds: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
