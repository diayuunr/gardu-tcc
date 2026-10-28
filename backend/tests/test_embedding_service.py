import logging

import pytest

from app.agents import embedding_service
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_generate_embedding_returns_vector_of_expected_dimension(monkeypatch):
    requested_dimensionality = []

    class _FakeEmbeddingsClient:
        def __init__(self, **_kwargs):
            pass

        def embed_query(self, _text, output_dimensionality=None):
            requested_dimensionality.append(output_dimensionality)
            return [0.01] * embedding_service.EMBEDDING_DIMENSIONS

    monkeypatch.setattr(embedding_service, "GoogleGenerativeAIEmbeddings", _FakeEmbeddingsClient)

    result = embedding_service.generate_embedding("Ada kejadian mencurigakan di jalan.")

    assert result is not None
    assert len(result) == embedding_service.EMBEDDING_DIMENSIONS
    # gemini-embedding-001 dimensi native-nya 3072 — pastikan kita eksplisit
    # minta 768 supaya tetap konsisten dengan kolom vector(768) di Supabase.
    assert requested_dimensionality == [768]


def test_embedding_failure_log_never_contains_report_text(monkeypatch, caplog):
    """Request embedding memuat teks laporan; pesan error pustaka bisa ikut
    memuatnya — log hanya boleh berisi tipe error + lokasi kode."""

    class _BrokenEmbeddingsClient:
        def __init__(self, **_kwargs):
            pass

        def embed_query(self, _text, output_dimensionality=None):
            raise RuntimeError("gagal memproses RAHASIA-LAPORAN nomor hp 081234567890")

    monkeypatch.setattr(embedding_service, "GoogleGenerativeAIEmbeddings", _BrokenEmbeddingsClient)

    with caplog.at_level(logging.DEBUG, logger="app.agents.embedding_service"):
        result = embedding_service.generate_embedding("RAHASIA-LAPORAN nomor hp 081234567890")

    assert result is None
    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert any("RuntimeError" in record.getMessage() for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)


def test_generate_embedding_returns_none_without_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()

    def fail_if_called(**_kwargs):
        raise AssertionError("Tidak boleh memanggil Gemini kalau API key belum diset")

    monkeypatch.setattr(embedding_service, "GoogleGenerativeAIEmbeddings", fail_if_called)

    result = embedding_service.generate_embedding("Teks apa saja")

    assert result is None
