from functools import lru_cache

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

    cors_allow_origins: str = "http://localhost:3000"

    # REQ-NF-122: batasi laporan per IP dalam rentang waktu singkat.
    rate_limit_max_requests: int = 5
    rate_limit_window_seconds: int = 600

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

    # REQ-F-020/022/023: parameter Risk Prediction Agent. SEMUA nilai di bawah
    # adalah ASUMSI SIMULASI tim (SRS Assumptions #5: seed data = simulasi, bukan
    # klaim data resmi kepolisian) — disetel lewat env, bukan fakta empiris.
    risk_grid_cell_degrees: float = 0.01  # sisi sel area ~1,1 km
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

    # REQ-F-030..032: parameter Safe Route Advisor (asumsi simulasi, disetel lewat env).
    route_sample_step_meters: int = 250  # jarak antar titik cek di sepanjang rute (sel grid ~1,1 km)
    route_max_samples: int = 400  # batas titik cek per rute; rute sangat panjang dijarangkan
    # Aturan status rute berbasis paparan (lihat docstring app/agents/route_agent.py).
    route_min_high_cells: int = 1  # jumlah sel "tinggi" dilintasi agar rute berisiko_tinggi
    route_min_medium_cells: int = 2  # jumlah sel "sedang" dilintasi agar rute waspada
    # Satu sel dengan skor >= ini membuat rute berisiko_tinggi walau jumlah sel "tinggi"
    # kurang dari route_min_high_cells.
    route_critical_score_threshold: float = 8.5
    # data_limited=true bila cakupan data (areas_with_data/areas_checked) <= ini.
    # 0.0 = hanya bila TIDAK ADA data sama sekali pada rute.
    route_limited_coverage_threshold: float = 0.0
    route_max_alternatives: int = 2  # rute alternatif Mapbox yang ikut dinilai (maks)
    # Alternatif hanya disarankan bila levelnya lebih rendah, atau levelnya sama dan skor
    # tertingginya lebih rendah sedikitnya sekian poin (hindari saran karena selisih sepele).
    route_alternative_min_score_gain: float = 0.5
    # Hasil geocoding teks yang jatuh dalam radius ini dari pusat kota/kabupaten dianggap
    # "pusat wilayah" (Mapbox sering mengembalikan pusat kota untuk nama yang tidak dikenal).
    route_geocode_generic_radius_meters: int = 500
    # Satu pemeriksaan rute = 2 geocoding + 1 Directions (+ Gemini): batas per-IP terpisah dari laporan.
    route_check_rate_limit_max_requests: int = 20
    route_check_rate_limit_window_seconds: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
