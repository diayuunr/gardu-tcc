import logging

import pytest

from app.agents import gemini_narration, route_narrator
from app.agents.route_narrator import RouteNarrativeFacts, generate_route_narrative, render_route_facts
from app.core.config import get_settings


def _facts(**overrides) -> RouteNarrativeFacts:
    values = dict(
        route_level="berisiko_tinggi",
        max_risk_score=7.6,
        time_buckets=("sore", "malam"),
        avoid_places=("Kotagede",),
        watch_places=("Umbulharjo",),
        distance_km=4.8,
        duration_minutes=21,
        areas_checked=9,
        areas_with_data=2,
    )
    values.update(overrides)
    return RouteNarrativeFacts(**values)


@pytest.fixture(autouse=True)
def narration_ready(monkeypatch):
    """Key palsu (Gemini asli TIDAK pernah dipanggil) + pengaman narasi bersih."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-not-real")
    get_settings.cache_clear()
    monkeypatch.setattr(gemini_narration, "gemini_narration_guard", gemini_narration.NarrationGuard())
    yield
    get_settings.cache_clear()


def test_narrative_for_risky_route_uses_only_aggregate_facts(monkeypatch):
    prompts = []

    def fake_invoke(facts, _api_key):
        prompts.append(render_route_facts(facts))
        return '  **Rute melewati Kotagede** pada malam hari; skor terbatas pada data yang ada. '

    monkeypatch.setattr(route_narrator, "_invoke_route_narration", fake_invoke)

    text = generate_route_narrative(_facts())

    assert text == "Rute melewati Kotagede pada malam hari; skor terbatas pada data yang ada."
    prompt = prompts[0]
    assert "Status rute: berisiko tinggi" in prompt and "dihindari (berisiko tinggi): Kotagede" in prompt
    assert "sore (15.00-18.00 WIB), lalu malam (18.00-24.00 WIB)" in prompt
    assert "skor tersedia untuk 2 dari 9 area" in prompt
    assert "Area -7." not in prompt  # tanpa label/koordinat grid


def test_safe_route_or_missing_key_never_calls_gemini(monkeypatch):
    calls = []
    monkeypatch.setattr(route_narrator, "_invoke_route_narration", lambda *_a: calls.append(1) or "x")

    assert generate_route_narrative(_facts(route_level="aman")) is None

    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    assert generate_route_narrative(_facts()) is None
    assert calls == []


def test_gemini_failure_returns_none_without_leaking_and_starts_cooldown(monkeypatch, caplog):
    def failing(_facts, _api_key):
        raise RuntimeError("429 kuota habis RAHASIA-PROMPT 081234567890")

    monkeypatch.setattr(route_narrator, "_invoke_route_narration", failing)

    with caplog.at_level(logging.DEBUG):
        assert generate_route_narrative(_facts()) is None

    assert gemini_narration.gemini_narration_guard.cooling_down()  # narasi rute & skor berbagi masa jeda
    assert "RAHASIA-PROMPT" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
