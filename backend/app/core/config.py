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

    # REQ-F-020/022/023: parameter Risk Prediction Agent. SEMUA nilai di bawah
    # adalah ASUMSI SIMULASI tim (SRS Assumptions #5: seed data = simulasi, bukan
    # klaim data resmi kepolisian) — disetel lewat env, bukan fakta empiris.
    risk_grid_cell_degrees: float = 0.01  # sisi sel area ~1,1 km
    risk_recency_half_life_days: int = 1825  # kejadian 5 tahun lalu berbobot separuh
    risk_score_saturation_scale: float = 1.0  # makin kecil = skor makin cepat jenuh menuju 10
    risk_level_medium_threshold: float = 3.0  # skor >= ini -> "sedang"
    risk_level_high_threshold: float = 7.0  # skor >= ini -> "tinggi"
    risk_ramadan_lead_days: int = 14  # jendela "jelang Ramadan" sebelum 1 Ramadan
    risk_ramadan_multiplier: float = 1.3  # pengali jelang + selama Ramadan (REQ-F-023)
    risk_ramadan_dini_hari_multiplier: float = 1.2  # tambahan saat Ramadan di jam sahur/SOTR

    # REQ-F-030..032: parameter Safe Route Advisor (asumsi simulasi, disetel lewat env).
    route_sample_step_meters: int = 250  # jarak antar titik cek di sepanjang rute (sel grid ~1,1 km)
    route_max_samples: int = 400  # batas titik cek per rute; rute sangat panjang dijarangkan
    # Satu pemeriksaan rute = 2 geocoding + 1 Directions (+ Gemini): batas per-IP terpisah dari laporan.
    route_check_rate_limit_max_requests: int = 20
    route_check_rate_limit_window_seconds: int = 600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
