import logging
import time

import pytest
from google.api_core.exceptions import ResourceExhausted
from langchain_google_genai.chat_models import _create_retry_decorator

import app.main  # noqa: F401 — import ini memasang filter log pustaka (silence_library_retry_logs)

_SECRET = "RAHASIA-LAPORAN nomor hp 081234567890"
_LIBRARY_LOGGER_NAME = "langchain_google_genai.chat_models"


def _run_real_library_retry(monkeypatch):
    """Jalankan jalur retry ASLI pustaka (tenacity + before_sleep_log) dengan
    error yang pesannya memuat data sensitif. Sleep dipatch supaya cepat."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    @_create_retry_decorator()
    def failing_call():
        raise ResourceExhausted(f"429 gagal memproses: {_SECRET}")

    with pytest.raises(ResourceExhausted):
        failing_call()


def test_control_without_our_filter_the_library_leaks_the_raw_message(monkeypatch, caplog):
    """KONTROL: tanpa filter kita, log retry pustaka memang membocorkan pesan
    error mentah. Tanpa ini, test di bawah bisa lulus 'karena kosong'."""
    monkeypatch.setattr(logging.getLogger(_LIBRARY_LOGGER_NAME), "filters", [])

    with caplog.at_level(logging.DEBUG):
        _run_real_library_retry(monkeypatch)

    assert "Retrying" in caplog.text
    assert "RAHASIA-LAPORAN" in caplog.text


def test_library_retry_log_never_leaks_raw_error_message(monkeypatch, caplog):
    with caplog.at_level(logging.DEBUG):
        _run_real_library_retry(monkeypatch)

    assert "RAHASIA-LAPORAN" not in caplog.text
    assert "081234567890" not in caplog.text
    assert "Retrying" not in caplog.text


def test_other_useful_library_warnings_are_still_visible(caplog):
    """Filter hanya membuang 'Retrying ...'. Warning alasan blokir safety filter
    milik pustaka (penjelasan langsung untuk hasil ekstraksi kosong) harus
    tetap muncul — makanya bukan sekadar menaikkan level logger ke ERROR."""
    library_logger = logging.getLogger(_LIBRARY_LOGGER_NAME)

    with caplog.at_level(logging.DEBUG):
        library_logger.warning(
            "Gemini produced an empty response. Continuing with empty message\n"
            "Feedback: block_reason: SAFETY"
        )

    assert "Gemini produced an empty response" in caplog.text
