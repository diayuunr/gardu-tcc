import logging

import pytest
from google.api_core.exceptions import ResourceExhausted

from app.agents import verify_agent
from app.core.config import get_settings

_RATE_LIMIT_MESSAGE = (
    "429 You exceeded your current quota. * Quota exceeded for metric: "
    "generate_content_free_tier_requests, limit: 15\nPlease retry in {seconds}s."
)


@pytest.fixture(autouse=True)
def _gemini_key_and_no_real_sleep(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    sleeps: list[float] = []
    monkeypatch.setattr(verify_agent.time, "sleep", sleeps.append)
    yield sleeps
    get_settings.cache_clear()


def _raise_rate_limit(seconds="25.08"):
    raise ResourceExhausted(_RATE_LIMIT_MESSAGE.format(seconds=seconds))


def test_retries_after_rate_limit_then_succeeds(monkeypatch, _gemini_key_and_no_real_sleep):
    sleeps = _gemini_key_and_no_real_sleep
    calls = {"count": 0}

    def flaky_invoke(_description, _api_key):
        calls["count"] += 1
        if calls["count"] == 1:
            _raise_rate_limit()
        return verify_agent.ExtractedEntities(incident_type="penyerangan")

    monkeypatch.setattr(verify_agent, "_invoke_extraction", flaky_invoke)

    result = verify_agent.extract_incident_type("Ada penyerangan di jalan.")

    assert result == "penyerangan"
    assert calls["count"] == 2
    # Menunggu sesuai retry_delay dari server (25.08s) + 1s margin.
    assert sleeps == [pytest.approx(26.08)]


def test_gives_up_after_max_retries_and_logs_rate_limit(monkeypatch, caplog, _gemini_key_and_no_real_sleep):
    sleeps = _gemini_key_and_no_real_sleep
    monkeypatch.setattr(verify_agent, "_invoke_extraction", lambda _d, _k: _raise_rate_limit())

    with caplog.at_level(logging.WARNING, logger="app.agents.verify_agent"):
        result = verify_agent.extract_incident_type("Ada penyerangan di jalan.")

    assert result is None
    assert len(sleeps) == verify_agent._RATE_LIMIT_MAX_RETRIES
    # Kegagalan tidak boleh diam-diam: harus ada log ERROR yang menyebut 429.
    assert any(
        r.levelno == logging.ERROR and "rate limit Gemini (429)" in r.getMessage()
        for r in caplog.records
    )


def test_retries_when_server_asks_for_49_seconds(monkeypatch, _gemini_key_and_no_real_sleep):
    """Regresi dari tes live: limit per-menit nyata meminta 44-49 dtk. Batas
    tunggu 30 dtk yang lama membuat semua langsung menyerah tanpa retry."""
    sleeps = _gemini_key_and_no_real_sleep
    calls = {"count": 0}

    def flaky_invoke(_description, _api_key):
        calls["count"] += 1
        if calls["count"] == 1:
            _raise_rate_limit(seconds="49.0")
        return verify_agent.ExtractedEntities(incident_type="tawuran")

    monkeypatch.setattr(verify_agent, "_invoke_extraction", flaky_invoke)

    result = verify_agent.extract_incident_type("Ada tawuran di simpang.")

    assert result == "tawuran"
    assert sleeps == [pytest.approx(50.0)]


def test_validation_error_log_never_contains_report_text(monkeypatch, caplog):
    """Log kegagalan skema hanya boleh memuat nama field + tipe error — tidak
    boleh ada input_value/teks laporan (bisa berisi data pribadi) dan tidak
    boleh ada traceback yang membawa pesan bawaan Pydantic."""
    secret_text = "RAHASIA-LAPORAN nomor hp 081234567890 nama Budi"

    def wrong_key_invoke(_description, _api_key):
        # Meniru perilaku Gemini yang salah mengisi argumen tool: key `description`.
        return verify_agent.ExtractedEntities(**{"description": secret_text})

    monkeypatch.setattr(verify_agent, "_invoke_extraction", wrong_key_invoke)

    with caplog.at_level(logging.DEBUG, logger="app.agents.verify_agent"):
        result = verify_agent.extract_incident_type(secret_text)

    assert result is None
    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert "input_value" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert any("incident_type: missing" in r.getMessage() for r in caplog.records)


def test_does_not_retry_when_server_delay_is_too_long(monkeypatch, _gemini_key_and_no_real_sleep):
    """Mis. kuota harian habis: server minta tunggu berjam-jam, jangan menahan worker."""
    sleeps = _gemini_key_and_no_real_sleep
    monkeypatch.setattr(
        verify_agent, "_invoke_extraction", lambda _d, _k: _raise_rate_limit(seconds="3600")
    )

    result = verify_agent.extract_incident_type("Ada penyerangan di jalan.")

    assert result is None
    assert sleeps == []


def test_non_rate_limit_error_is_logged_not_retried(monkeypatch, caplog, _gemini_key_and_no_real_sleep):
    sleeps = _gemini_key_and_no_real_sleep

    def broken_invoke(_description, _api_key):
        # Pesan error pustaka bisa memuat isi request (teks laporan).
        raise RuntimeError("gagal memproses RAHASIA-LAPORAN nomor hp 081234567890")

    monkeypatch.setattr(verify_agent, "_invoke_extraction", broken_invoke)

    with caplog.at_level(logging.WARNING, logger="app.agents.verify_agent"):
        result = verify_agent.extract_incident_type("Ada penyerangan di jalan.")

    assert result is None
    assert sleeps == []
    assert any(
        r.levelno == logging.ERROR and "RuntimeError" in r.getMessage() for r in caplog.records
    )
    # Celah log ditutup: tanpa pesan error mentah dan tanpa traceback.
    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_tool_description_sent_to_model_has_no_developer_notes():
    """Regresi: docstring class DIKIRIM ke Gemini sebagai deskripsi tool. Dulu
    berisi kata 'description' -> model ~37% salah mengisi argumen bernama
    `description` (bukan `incident_type`) -> validasi gagal -> hasil NULL.
    """
    doc = verify_agent.ExtractedEntities.__doc__ or ""

    assert "description" not in doc.lower()
    assert len(doc) < 100


def test_empty_structured_output_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(verify_agent, "_invoke_extraction", lambda _d, _k: None)

    with caplog.at_level(logging.WARNING, logger="app.agents.verify_agent"):
        result = verify_agent.extract_incident_type("Teks yang diblokir safety filter.")

    assert result is None
    assert any("hasil kosong" in r.getMessage() for r in caplog.records)
