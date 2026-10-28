from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from app.core.config import get_settings


@lru_cache
def get_supabase() -> Client:
    """Client Supabase sisi server (service role key, bypass RLS).

    Hanya dipakai di backend setelah request tervalidasi lewat endpoint API,
    sesuai aturan SECURITY BY DESIGN di CLAUDE.md. Jangan expose service
    role key ke frontend. Timeout query dari `supabase_timeout_seconds` (bawaan library 120 dtk
    terlalu lama untuk endpoint yang dilihat pengguna).
    """
    settings = get_settings()
    return create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=ClientOptions(postgrest_client_timeout=settings.supabase_timeout_seconds),
    )
