import logging
import threading
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents import gemini_narration, risk_narrator
from app.agents.risk_agent import WIB, RiskLookup
from app.agents.risk_narrator import (
    JELANG_RAMADAN,
    SELAMA_RAMADAN,
    build_narrative_facts,
    clean_narrative,
    generate_risk_narrative,
    render_facts,
)
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)

AREA_LABEL = "Area -7.815, 110.395"
NORMAL_DAY = datetime(2026, 9, 20, 12, 0, tzinfo=WIB)
PRE_RAMADAN_DAY = datetime(2027, 1, 30, 12, 0, tzinfo=WIB)  # Ramadan 1448 H mulai 8 Feb 2027
DURING_RAMADAN_DAY = datetime(2027, 2, 20, 12, 0, tzinfo=WIB)


def _lookup(**overrides) -> RiskLookup:
    values = dict(
        area_name=AREA_LABEL, time_bucket="malam", risk_score=4.17, risk_level="sedang",
        contributing_incident_count=1, has_data=True, last_calculated_at=NORMAL_DAY,
    )
    values.update(overrides)
    return RiskLookup(**values)


@pytest.fixture(autouse=True)
def narrator_state(monkeypatch):
    """API key palsu (Gemini asli TIDAK pernah dipanggil: `_invoke_narration`
    di-mock tiap test), cache/jeda bersih, dan jam yang bisa dimajukan."""
    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key-not-real")
    get_settings.cache_clear()
    clock = {"now": 1000.0}
    _use_guard(monkeypatch, clock)
    yield clock
    get_settings.cache_clear()


def _use_guard(monkeypatch, clock, **guard_options):
    """Ganti pengaman narasi bersama dengan yang baru (cache/jeda/slot bersih)
    dan jam yang bisa dimajukan lewat `clock["now"]`."""
    guard = gemini_narration.NarrationGuard(clock=lambda: clock["now"], **guard_options)
    monkeypatch.setattr(gemini_narration, "gemini_narration_guard", guard)
    return guard


@pytest.fixture
def gemini_calls(monkeypatch):
    """Ganti panggilan Gemini dengan narasi tetap; kembalikan daftar fakta yang diminta."""
    calls: list[risk_narrator.NarrativeFacts] = []

    def fake_invoke(facts, _api_key):
        calls.append(facts)
        return "Skor sedang karena ada satu insiden tercatat di jam malam."

    monkeypatch.setattr(risk_narrator, "_invoke_narration", fake_invoke)
    return calls


class _SingleRowSupabase:
    """Supabase palsu minimal: query chain apa pun berakhir di satu baris `risk_scores`."""

    def __init__(self, row):
        self._row = row

    def table(self, _name):
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[self._row])


def _get_score_endpoint(row, include_narrative: str | None = "true"):
    """Default meminta narasi; `None` = tanpa parameter (perilaku default endpoint)."""
    params = {"lat": -7.812995, "lon": 110.39872, "at": "2026-09-20T22:30:00"}
    if include_narrative is not None:
        params["include_narrative"] = include_narrative
    app.dependency_overrides[get_supabase] = lambda: _SingleRowSupabase(row)
    try:
        return client.get("/risk/score", params=params)
    finally:
        app.dependency_overrides.pop(get_supabase, None)


_STORED_ROW = {
    "risk_score": 4.17, "risk_level": "sedang", "contributing_incident_count": 1,
    "last_calculated_at": "2026-09-20T05:00:00+00:00",
}


# ------------------------------------------------------------- endpoint


def test_default_request_is_the_fast_path_and_never_touches_gemini(gemini_calls, monkeypatch):
    """Jalur heatmap: tanpa include_narrative (atau =false) hanya baca DB, Gemini
    tidak dipanggil — bahkan kalau Gemini sedang menggantung, respons tetap cepat."""
    for value in (None, "false"):
        response = _get_score_endpoint(_STORED_ROW, include_narrative=value)
        body = response.json()
        assert response.status_code == 200
        assert body["narrative"] is None
        assert (body["risk_score"], body["risk_level"]) == (4.17, "sedang")  # skor sedang tetap utuh
    assert gemini_calls == []

    release = threading.Event()
    monkeypatch.setattr(risk_narrator, "_invoke_narration", lambda _facts, _key: release.wait(5) and "lambat")
    started = time.monotonic()
    try:
        _get_score_endpoint(_STORED_ROW, include_narrative=None)
    finally:
        release.set()
    assert time.monotonic() - started < 1.0  # tidak menunggu Gemini sama sekali


def test_include_narrative_is_validated_at_the_api_level(gemini_calls):
    assert _get_score_endpoint(_STORED_ROW, include_narrative="mungkin").status_code == 422
    assert gemini_calls == []


def test_endpoint_adds_narrative_for_medium_score_without_changing_the_numbers(gemini_calls):
    response = _get_score_endpoint(_STORED_ROW)

    body = response.json()
    assert response.status_code == 200
    assert body["narrative"] == "Skor sedang karena ada satu insiden tercatat di jam malam."
    # Angka tetap dari data tersimpan/rumus — narasi tidak menyentuhnya.
    assert (body["risk_score"], body["risk_level"], body["contributing_incident_count"]) == (4.17, "sedang", 1)
    assert len(gemini_calls) == 1
    assert (gemini_calls[0].risk_score, gemini_calls[0].time_bucket) == (4.17, "malam")


def test_endpoint_still_returns_score_when_gemini_fails_and_skips_gemini_during_cooldown(
    monkeypatch, caplog, narrator_state
):
    attempts = []

    def rate_limited(_facts, _key):
        attempts.append(1)
        raise RuntimeError("429 quota habis RAHASIA-PROMPT 081234567890")

    monkeypatch.setattr(risk_narrator, "_invoke_narration", rate_limited)

    with caplog.at_level(logging.DEBUG):
        first = _get_score_endpoint(_STORED_ROW)
        second = _get_score_endpoint(_STORED_ROW)  # dalam masa jeda: Gemini TIDAK dipanggil lagi
        narrator_state["now"] += gemini_narration.gemini_narration_guard.failure_cooldown_seconds + 1
        third = _get_score_endpoint(_STORED_ROW)  # jeda habis: dicoba lagi

    for response in (first, second, third):
        assert response.status_code == 200  # endpoint TIDAK gagal gara-gara narasi
        assert response.json()["narrative"] is None
        assert response.json()["risk_score"] == 4.17
    assert len(attempts) == 2  # percobaan pertama + percobaan setelah jeda; request kedua dilewati
    assert "RAHASIA-PROMPT" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_hanging_gemini_call_is_cut_at_the_deadline_and_score_still_returned(monkeypatch, narrator_state):
    """Regresi uji nyata: saat 429 library menahan request ~38 dtk. Request
    tidak boleh ikut menunggu selama itu."""
    release = threading.Event()
    guard = _use_guard(monkeypatch, narrator_state, deadline_seconds=0.05)
    monkeypatch.setattr(risk_narrator, "_invoke_narration", lambda _facts, _key: release.wait(5) and "terlambat")

    started = time.monotonic()
    try:
        response = _get_score_endpoint(_STORED_ROW)
    finally:
        release.set()  # bebaskan pekerja latar supaya tidak menahan test lain

    assert time.monotonic() - started < 2.0  # jauh di bawah 5 dtk "panggilan menggantung"
    assert response.status_code == 200
    assert response.json()["narrative"] is None
    assert response.json()["risk_score"] == 4.17
    assert guard.cooling_down()  # masuk masa jeda, tidak menumpuk pekerja baru


def test_third_request_gets_none_immediately_when_both_slots_are_busy(monkeypatch):
    """2 slot terpakai (Gemini lambat) -> request ke-3 TIDAK antre dan TIDAK
    menunggu: langsung tanpa narasi, tanpa memanggil Gemini, tanpa masa jeda."""
    release = threading.Event()
    entered = threading.Semaphore(0)
    invocations = []

    def slow_gemini(facts, _key):
        invocations.append(facts.risk_score)
        entered.release()
        release.wait(5)
        return "Narasi dari panggilan yang lambat."

    monkeypatch.setattr(risk_narrator, "_invoke_narration", slow_gemini)
    results = {}

    def request(score):
        results[score] = generate_risk_narrative(_lookup(risk_score=score))

    busy_threads = [threading.Thread(target=request, args=(score,)) for score in (4.1, 4.2)]
    try:
        for thread in busy_threads:
            thread.start()
        assert entered.acquire(timeout=2) and entered.acquire(timeout=2)  # kedua slot terpakai

        started = time.monotonic()
        third = generate_risk_narrative(_lookup(risk_score=4.3))
        elapsed = time.monotonic() - started

        assert third is None
        assert elapsed < 0.5  # tidak menunggu slot & tidak menunggu Gemini
        assert sorted(invocations) == [4.1, 4.2]  # request ke-3 tidak sampai ke Gemini
        assert not gemini_narration.gemini_narration_guard.cooling_down()  # "penuh" bukan kegagalan Gemini
    finally:
        release.set()
        for thread in busy_threads:
            thread.join(timeout=5)

    assert results == {4.1: "Narasi dari panggilan yang lambat.", 4.2: "Narasi dari panggilan yang lambat."}
    # Slot sudah dilepas pekerja: request berikutnya dilayani normal.
    assert generate_risk_narrative(_lookup(risk_score=4.4)) == "Narasi dari panggilan yang lambat."


def test_slots_are_released_after_failures_and_timeouts(monkeypatch, narrator_state):
    """Slot tidak boleh bocor: gagal 3x berturut-turut (lebih banyak dari jumlah
    slot) lalu panggilan sukses tetap dilayani."""
    guard = _use_guard(monkeypatch, narrator_state, deadline_seconds=0.05)
    outcomes = ["error", "hang", "error", "ok"]
    release = threading.Event()

    def flaky_gemini(_facts, _key):
        outcome = outcomes.pop(0)
        if outcome == "error":
            raise RuntimeError("gagal")
        if outcome == "hang":
            release.wait(5)  # melewati batas waktu, tapi nanti selesai sendiri
        return "Narasi berhasil."

    monkeypatch.setattr(risk_narrator, "_invoke_narration", flaky_gemini)

    try:
        for _ in range(3):
            assert generate_risk_narrative(_lookup()) is None
            narrator_state["now"] += guard.failure_cooldown_seconds + 1  # lewati masa jeda
    finally:
        release.set()  # panggilan yang menggantung selesai -> pekerja melepas slotnya
        time.sleep(0.2)

    assert generate_risk_narrative(_lookup()) == "Narasi berhasil."


# -------------------------------------------------- pemicu, cache, validasi keluaran


def test_no_narrative_for_low_score_missing_data_or_missing_api_key(gemini_calls, monkeypatch):
    assert generate_risk_narrative(_lookup(risk_level="rendah", risk_score=1.2)) is None
    assert generate_risk_narrative(_lookup(has_data=False, risk_level="rendah", risk_score=0.0)) is None
    assert gemini_calls == []

    monkeypatch.setenv("GEMINI_API_KEY", "")
    get_settings.cache_clear()
    assert generate_risk_narrative(_lookup()) is None
    assert gemini_calls == []


def test_same_facts_hit_cache_but_changed_score_asks_gemini_again(gemini_calls, narrator_state):
    generate_risk_narrative(_lookup())
    generate_risk_narrative(_lookup(area_name="Area -7.700, 110.300"))  # fakta sama -> narasi sama
    assert len(gemini_calls) == 1

    generate_risk_narrative(_lookup(risk_score=6.9, risk_level="sedang"))  # skor dihitung ulang
    assert len(gemini_calls) == 2

    narrator_state["now"] += gemini_narration.gemini_narration_guard.cache_ttl_seconds + 1  # TTL habis
    generate_risk_narrative(_lookup())
    assert len(gemini_calls) == 3


@pytest.mark.parametrize("raw", ["", "   \n ", "x" * 600])
def test_empty_or_overlong_model_output_is_rejected(raw, monkeypatch):
    assert clean_narrative(raw) is None
    monkeypatch.setattr(risk_narrator, "_invoke_narration", lambda _facts, _key: raw)
    assert generate_risk_narrative(_lookup()) is None


def test_clean_narrative_strips_markdown_and_extra_whitespace():
    assert clean_narrative('  **Skor** sedang.\n\nWaspadai jam malam. ') == "Skor sedang. Waspadai jam malam."


# --------------------------------------------------------------- fakta & prompt


def test_season_facts_follow_the_date_the_score_was_calculated():
    settings = get_settings()

    normal = build_narrative_facts(_lookup(last_calculated_at=NORMAL_DAY), settings)
    assert (normal.season_known, normal.season, normal.season_multiplier) == (True, None, 1.0)

    pre = build_narrative_facts(_lookup(last_calculated_at=PRE_RAMADAN_DAY), settings)
    assert (pre.season, pre.season_multiplier) == (JELANG_RAMADAN, settings.risk_ramadan_multiplier)

    sahur = build_narrative_facts(
        _lookup(time_bucket="dini_hari", last_calculated_at=DURING_RAMADAN_DAY), settings
    )
    assert sahur.season == SELAMA_RAMADAN
    assert sahur.season_multiplier == pytest.approx(
        settings.risk_ramadan_multiplier * settings.risk_ramadan_dini_hari_multiplier
    )
    assert "sahur" in render_facts(sahur)

    unknown = build_narrative_facts(_lookup(last_calculated_at=None), settings)
    assert unknown.season_known is False
    assert "jangan menyinggung musim" in render_facts(unknown)


def test_prompt_sent_to_gemini_has_only_aggregate_facts_and_output_is_parsed(monkeypatch):
    """Menguji rangkaian prompt | model | parser dengan model palsu (tanpa jaringan)."""
    sent_messages = []

    def fake_llm(prompt_value):
        sent_messages.extend(prompt_value.to_messages())
        return AIMessage(content='  "Skor sedang karena satu insiden di jam malam."  ')

    monkeypatch.setattr(gemini_narration, "ChatGoogleGenerativeAI", lambda **_kwargs: RunnableLambda(fake_llm))

    text = risk_narrator._invoke_narration(
        build_narrative_facts(_lookup(last_calculated_at=PRE_RAMADAN_DAY), get_settings()), "dummy-key-not-real"
    )

    prompt_text = "\n".join(message.content for message in sent_messages)
    assert "4.17 dari 10 (tingkat: sedang)" in prompt_text
    assert "menjelang Ramadan" in prompt_text
    assert "Area -7.815" not in prompt_text  # label/koordinat area tidak ikut dikirim
    assert clean_narrative(text) == "Skor sedang karena satu insiden di jam malam."
