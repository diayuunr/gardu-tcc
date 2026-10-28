"""Infrastruktur bersama lapisan narasi Gemini (Risk Prediction & Safe Route Advisor).

SATU-SATUNYA tempat model narasi dipilih, chain LangChain dibangun, dan
panggilan Gemini dikendalikan, supaya narasi skor risiko dan narasi rute
berbagi kuota free tier (15 request/menit per model) dan tidak ada panggilan
AI mentah yang tersebar di banyak file.

Prinsip: narasi itu tambahan, BUKAN syarat. `NarrationGuard.run` tidak pernah
melempar exception dan mengembalikan None kalau Gemini tidak siap (rate limit
429, timeout, penuh, output kosong/aneh) — pemanggil tetap mengembalikan
hasil deterministiknya.

Perlindungan (per proses, in-memory):
- Batas waktu keras (`deadline_seconds`) di atas timeout HTTP: request tidak
  pernah menunggu lebih lama dari itu walau library sedang retry saat 429
  (uji nyata: request bisa tertahan ~38 dtk).
- Maksimal `max_concurrent` (2) panggilan bersamaan lewat semaphore
  non-blocking: request lain langsung tanpa narasi, tidak antre. Slot dilepas
  PEKERJA saat panggilan benar-benar selesai (bukan saat request menyerah),
  karena panggilan macet tidak bisa dibatalkan dan tetap memakai kuota.
- Cache per kunci fakta: fakta yang sama tidak memanggil Gemini ulang selama TTL.
- Setelah SATU kegagalan, narasi dilewati selama masa jeda tanpa memanggil
  Gemini — request lain tidak ikut menunggu timeout/429. "Penuh" BUKAN kegagalan
  dan tidak memicu masa jeda.

KNOWN LIMITATIONS: cache/jeda/slot berlaku per proses; dua request bersamaan
untuk kunci yang sama (belum ter-cache) masing-masing memakai satu slot
(tidak ada single-flight); panggilan yang melewati batas waktu hasilnya dibuang.
"""

import logging
import threading
import time
from collections.abc import Callable, Hashable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

# Model valid per list_models (dicek saat modul ini dibuat). Alias "-latest"
# dipakai supaya tidak kena retirement model ter-pin (lihat verify_agent.py).
# Sengaja "flash-lite": uji nyata ~1 dtk & stabil, sedangkan "gemini-flash-latest"
# ~4 dtk dan sempat 503 (overloaded) + 429. Kuotanya berbagi dengan Verification
# Agent, tapi pemakaian narasi kecil berkat cache & masa jeda.
NARRATION_MODEL = "models/gemini-flash-lite-latest"

_HTTP_TIMEOUT_SECONDS = 5  # timeout HTTP satu percobaan
_MAX_NARRATIVE_CHARS = 500  # 1-2 kalimat wajar jauh di bawah ini; lebih = model tidak patuh


def build_narration_chain(system_prompt: str, human_template: str, api_key: str) -> Runnable:
    """Chain LangChain (prompt | Gemini | parser teks). `human_template` harus
    memuat placeholder `{facts}`. Suhu rendah: menjelaskan fakta, bukan berkreasi."""
    prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", human_template)])
    llm = ChatGoogleGenerativeAI(
        model=NARRATION_MODEL,
        google_api_key=api_key,
        timeout=_HTTP_TIMEOUT_SECONDS,
        temperature=0.2,
    )
    return prompt | llm | StrOutputParser()


def clean_narrative(raw: str) -> str | None:
    """Rapikan keluaran model; kosong atau terlalu panjang -> None (ditolak)."""
    text = " ".join(raw.replace("**", "").split()).strip('"“” ')
    if not text or len(text) > _MAX_NARRATIVE_CHARS:
        return None
    return text


class NarrationBusy(Exception):
    """Semua slot panggilan Gemini sedang dipakai; narasi dilewati tanpa menunggu."""


class NarrationGuard:
    """Pengendali panggilan narasi: cache, masa jeda gagal, batas waktu, dan slot."""

    def __init__(
        self,
        *,
        max_concurrent: int = 2,
        deadline_seconds: float = 7.0,
        cache_ttl_seconds: float = 3600.0,
        cache_max_entries: int = 256,
        failure_cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.deadline_seconds = deadline_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.failure_cooldown_seconds = failure_cooldown_seconds
        self._cache_max_entries = cache_max_entries
        self._clock = clock
        # Jumlah slot = jumlah pekerja, jadi pekerjaan tidak pernah antre di executor.
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent, thread_name_prefix="narration")
        self._lock = threading.Lock()
        self._cache: dict[Hashable, tuple[str, float]] = {}  # kunci -> (narasi, waktu kedaluwarsa)
        self._cooldown_until = 0.0

    def cooling_down(self) -> bool:
        """True selama masa jeda setelah kegagalan Gemini."""
        with self._lock:
            return self._clock() < self._cooldown_until

    def run(self, key: Hashable, produce: Callable[[], str], clean: Callable[[str], str | None]) -> str | None:
        """Narasi untuk `key` (dari cache atau `produce()`), atau None. TIDAK PERNAH melempar."""
        now = self._clock()
        cached, cooling_down = self._lookup_state(key, now)
        if cached is not None:
            return cached
        if cooling_down:
            return None  # baru saja gagal; jangan menambah beban/menunggu timeout lagi

        try:
            text = clean(self._call_with_deadline(produce))
            if text is None:
                logger.warning("Narasi dilewati: Gemini mengembalikan teks kosong/terlalu panjang")
                self._start_cooldown()
                return None
            self._store(key, text)
            return text
        except NarrationBusy:
            # Bukan kegagalan Gemini, jadi TIDAK memicu masa jeda: cukup lewati
            # narasi untuk request ini; hasil deterministik tetap dikembalikan.
            logger.info("Narasi dilewati: semua slot panggilan Gemini sedang sibuk")
            return None
        except Exception as exc:  # noqa: BLE001 - narasi opsional: kegagalan apa pun tidak boleh sampai ke endpoint
            # Tanpa exc_info/pesan mentah library (lihat app/core/safe_log.py).
            logger.warning("Narasi dilewati: %s", safe_error_summary(exc))
            self._start_cooldown()
            return None

    def _lookup_state(self, key: Hashable, now: float) -> tuple[str | None, bool]:
        """(narasi tersimpan yang belum kedaluwarsa, sedang dalam masa jeda gagal?)"""
        with self._lock:
            entry = self._cache.get(key)
            cached = entry[0] if entry and entry[1] > now else None
            return cached, now < self._cooldown_until

    def _store(self, key: Hashable, text: str) -> None:
        now = self._clock()
        with self._lock:
            if len(self._cache) >= self._cache_max_entries:
                for stale_key in [k for k, (_, expires) in self._cache.items() if expires <= now]:
                    del self._cache[stale_key]
                if len(self._cache) >= self._cache_max_entries:
                    del self._cache[next(iter(self._cache))]  # buang yang paling lama masuk
            self._cache[key] = (text, now + self.cache_ttl_seconds)

    def _start_cooldown(self) -> None:
        with self._lock:
            self._cooldown_until = self._clock() + self.failure_cooldown_seconds

    def _call_with_deadline(self, produce: Callable[[], str]) -> str:
        """`produce()` di pekerja dengan batas waktu keras dan batas panggilan bersamaan.

        Semua slot sibuk -> NarrationBusy seketika (tanpa antre); lewat batas
        waktu -> TimeoutError.
        """
        slots = self._slots  # dipegang lokal supaya slot yang sama yang dilepas pekerja
        if not slots.acquire(blocking=False):
            raise NarrationBusy

        def run_and_release() -> str:
            try:
                return produce()
            finally:
                slots.release()  # sukses maupun gagal; dilepas PEKERJA, bukan saat request menyerah

        try:
            future = self._executor.submit(run_and_release)
        except BaseException:  # gagal submit (mis. executor sudah shutdown): jangan bocorkan slot
            slots.release()
            raise
        try:
            return future.result(timeout=self.deadline_seconds)
        except FutureTimeoutError as exc:
            raise TimeoutError(f"narasi melebihi batas {self.deadline_seconds:g} detik") from exc


# Satu pengendali untuk seluruh narasi Gemini di proses ini (kuota model dipakai bersama).
# Diakses lewat atribut modul (`gemini_narration.gemini_narration_guard`) supaya test bisa menggantinya.
gemini_narration_guard = NarrationGuard()
