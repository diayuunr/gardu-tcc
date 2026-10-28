import os

import httpx
import pytest

from app.core import rate_limit
from app.core.config import get_settings

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
# Supabase client cuma validasi format mirip JWT (3 bagian dipisah titik) saat
# dibuat, tidak melakukan panggilan jaringan — jadi aman dipakai sebagai dummy
# di test, bukan credential asli.
os.environ.setdefault(
    "SUPABASE_SERVICE_ROLE_KEY", "test.not-a-real-key.dummy"
)

# Host bawaan TestClient Starlette — satu-satunya tujuan request yang boleh di test.
_ALLOWED_TEST_HOSTS = {"testserver"}


@pytest.fixture(autouse=True)
def _no_real_api_credentials(monkeypatch):
    """Test TIDAK BOLEH memakai kuota API asli.

    backend/.env di mesin developer berisi token/key ASLI (Mapbox, Gemini),
    dan pydantic-settings membacanya kalau env var tidak diisi. Dikosongkan
    di sini untuk SEMUA test; test yang butuh key sendiri (dengan mock
    client-nya) tinggal monkeypatch.setenv di fixture/test-nya.
    """
    for name in ("MAPBOX_TOKEN", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Rate limiter (REQ-NF-122) menyimpan hitungan per-IP di dict global
    in-memory. Tanpa reset, tiap test yang memanggil POST /reports (termasuk
    yang berakhir 422) menghabiskan jatah test lain dan urutan test jadi
    menentukan lulus/gagal."""
    rate_limit._request_log.clear()
    yield
    rate_limit._request_log.clear()


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Lapisan kedua: request httpx ke host selain `testserver` menggagalkan
    test dengan pesan jelas, supaya panggilan API asli yang lolos mock
    ketahuan (bukan diam-diam memakai kuota)."""
    original_send = httpx.Client.send

    def guarded_send(self, request, *args, **kwargs):
        if request.url.host not in _ALLOWED_TEST_HOSTS:
            raise AssertionError(
                f"Test TIDAK boleh memanggil network asli: {request.method} {request.url.host}"
            )
        return original_send(self, request, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
