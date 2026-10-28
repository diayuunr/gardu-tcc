"""Cache daftar/statistik publik dikosongkan saat laporan masuk dan setelah verifikasi (juga bila verifikasi gagal)."""

import pytest

from app.api import reports as reports_module
from app.api import reports_public


def test_verifikasi_selalu_diikuti_pengosongan_cache(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(reports_module, "process_report_verification", lambda report_id: calls.append(f"verify:{report_id}"))
    monkeypatch.setattr(reports_module, "clear_public_cache", lambda: calls.append("clear"))

    reports_module._verify_then_refresh_public_cache("abc")

    assert calls == ["verify:abc", "clear"]


def test_cache_dikosongkan_walau_verifikasi_melempar_error(monkeypatch):
    calls: list[str] = []

    def boom(_report_id: str) -> None:
        raise RuntimeError("verifikasi gagal")

    monkeypatch.setattr(reports_module, "process_report_verification", boom)
    monkeypatch.setattr(reports_module, "clear_public_cache", lambda: calls.append("clear"))

    with pytest.raises(RuntimeError):
        reports_module._verify_then_refresh_public_cache("abc")

    assert calls == ["clear"]


def test_clear_public_cache_mengosongkan_kedua_cache():
    reports_public._list_cache[(20, 0)] = (10**12, object())  # type: ignore[assignment]
    reports_public._stats_cache["stats"] = (10**12, object())  # type: ignore[assignment]

    reports_public.clear_public_cache()

    assert not reports_public._list_cache
    assert not reports_public._stats_cache
