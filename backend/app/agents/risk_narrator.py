"""Lapisan narasi Risk Prediction Agent: Gemini MENJELASKAN skor, tidak menghitungnya.

Angka skor & tingkat tetap 100% berasal dari rumus deterministik di
`risk_agent.py`. Modul ini hanya mengubah angka yang sudah jadi (plus konteks
yang dipakai rumus: jam rawan, musim Ramadan, jumlah insiden) menjadi 1-2
kalimat Bahasa Indonesia untuk warga.

Prinsip: narasi itu tambahan, BUKAN syarat. `generate_risk_narrative` tidak
pernah melempar exception dan mengembalikan None kalau Gemini tidak siap
(API key kosong, rate limit 429, timeout, penuh, output kosong/aneh) — endpoint
tetap mengembalikan skor angka. Perlindungan kuota (batas waktu, 2 slot, cache,
masa jeda) ada di `gemini_narration.py` dan dipakai bersama narasi rute.

Data ke Gemini hanya angka agregat & label jam/musim: TANPA teks laporan,
lokasi, koordinat, atau identitas apa pun (REQ-NF-120/REQ-F-042).

KNOWN LIMITATION: isi narasi dijaga lewat prompt (fakta-saja, suhu rendah, batas
panjang), bukan diverifikasi otomatis kalimat demi kalimat — LLM masih bisa
salah memparafrasekan fakta.
"""

import logging
from dataclasses import dataclass

from app.agents import gemini_narration
from app.agents.gemini_narration import clean_narrative
from app.agents.risk_agent import (
    DINI_HARI,
    JELANG_RAMADAN,
    SELAMA_RAMADAN,
    TIME_BUCKET_HOURS,
    RiskLookup,
    ramadan_phase,
    seasonal_multiplier,
    to_wib,
)
from app.core.config import Settings, get_settings
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

_NARRATED_LEVELS = frozenset({"sedang", "tinggi"})

_SYSTEM_PROMPT = (
    "Kamu menulis penjelasan singkat untuk warga Yogyakarta tentang skor kerawanan "
    "sebuah area terhadap kejahatan jalanan (klitih) yang SUDAH dihitung oleh sistem. "
    "Tugasmu HANYA menjelaskan mengapa skornya segitu berdasarkan fakta yang diberikan.\n"
    "Aturan:\n"
    "- Tulis 1-2 kalimat Bahasa Indonesia yang tenang dan informatif, tanpa nada menakut-nakuti.\n"
    "- Pakai HANYA fakta yang diberikan. Jangan menambah angka, tanggal, nama tempat, "
    "kronologi kejadian, atau penyebab lain yang tidak ada di fakta.\n"
    "- Jangan menghitung ulang atau mempertanyakan skor; sebut tingkat kerawanan persis "
    "seperti yang diberikan.\n"
    "- Sebut jam rawan, jumlah insiden tercatat, dan pengaruh musim hanya bila ada di fakta. "
    "Kalau jumlah insiden sedikit, tunjukkan bahwa dasar datanya masih terbatas.\n"
    "- Jangan menyebut identitas pelaku/korban, jangan menjanjikan keamanan, dan jangan "
    "menyarankan tindakan main hakim sendiri.\n"
    "- Keluarkan hanya kalimat penjelasannya, tanpa judul, daftar, atau format markdown."
)
_HUMAN_TEMPLATE = "Fakta skor:\n{facts}\n\nTulis penjelasannya."


@dataclass(frozen=True)
class NarrativeFacts:
    """Seluruh masukan narasi. Frozen/hashable: sekaligus jadi kunci cache."""

    risk_score: float
    risk_level: str
    time_bucket: str
    incident_count: int
    season_known: bool  # False = waktu hitung skor tidak diketahui -> musim tidak disinggung
    season: str | None  # JELANG_RAMADAN / SELAMA_RAMADAN / None (di luar musim)
    season_multiplier: float  # pengali yang BENAR-BENAR tertanam di skor


# ---------------------------------------------------------------- fungsi murni


def build_narrative_facts(lookup: RiskLookup, settings: Settings) -> NarrativeFacts:
    """Susun fakta dari skor tersimpan. Musim dinilai pada WAKTU HITUNG skor
    (`last_calculated_at`), bukan waktu bertanya, karena itulah musim yang
    tertanam di angkanya; memakai logika yang sama dengan rumus (risk_agent)."""
    if lookup.last_calculated_at is None:
        return NarrativeFacts(
            risk_score=lookup.risk_score,
            risk_level=lookup.risk_level,
            time_bucket=lookup.time_bucket,
            incident_count=lookup.contributing_incident_count,
            season_known=False,
            season=None,
            season_multiplier=1.0,
        )
    calculated_on = to_wib(lookup.last_calculated_at).date()
    return NarrativeFacts(
        risk_score=lookup.risk_score,
        risk_level=lookup.risk_level,
        time_bucket=lookup.time_bucket,
        incident_count=lookup.contributing_incident_count,
        season_known=True,
        season=ramadan_phase(calculated_on, settings),
        season_multiplier=seasonal_multiplier(calculated_on, lookup.time_bucket, settings),
    )


def _describe_season(facts: NarrativeFacts) -> str:
    if not facts.season_known:
        return "tidak diketahui (jangan menyinggung musim)"
    if facts.season == JELANG_RAMADAN:
        return f"menjelang Ramadan; skor sudah dikali {facts.season_multiplier:.2f} karena pola historis kenaikan kasus"
    if facts.season == SELAMA_RAMADAN:
        extra = (
            " (sudah termasuk tambahan jam sahur/dini hari karena SOTR, singkatan dari \"sahur on the road\" "
            "yang dicatat marak sebagai pola kejahatan jalanan)"
            if facts.time_bucket == DINI_HARI
            else ""
        )
        return f"selama Ramadan; skor sudah dikali {facts.season_multiplier:.2f}{extra}"
    return "tidak ada pengaruh musim pada skor ini (jangan menyinggung musim atau Ramadan)"


def render_facts(facts: NarrativeFacts) -> str:
    """Fakta sebagai daftar teks untuk prompt."""
    start_hour, end_hour = next((s, e) for bucket, s, e in TIME_BUCKET_HOURS if bucket == facts.time_bucket)
    return "\n".join(
        [
            f"- Skor kerawanan: {facts.risk_score:.2f} dari 10 (tingkat: {facts.risk_level})",
            f"- Rentang waktu: {facts.time_bucket.replace('_', ' ')} ({start_hour:02d}.00-{end_hour:02d}.00 WIB)",
            f"- Jumlah insiden tercatat (data awal + laporan warga terverifikasi) di area dan rentang jam ini: {facts.incident_count}",
            f"- Musim saat skor dihitung: {_describe_season(facts)}",
        ]
    )


# ------------------------------------------------------------------- pemanggilan


def _invoke_narration(facts: NarrativeFacts, api_key: str) -> str:
    """Satu kali panggilan Gemini lewat chain LangChain bersama (gemini_narration).
    Exception dibiarkan naik ke NarrationGuard yang menanganinya."""
    chain = gemini_narration.build_narration_chain(_SYSTEM_PROMPT, _HUMAN_TEMPLATE, api_key)
    return chain.invoke({"facts": render_facts(facts)})


def generate_risk_narrative(lookup: RiskLookup) -> str | None:
    """Penjelasan 1-2 kalimat untuk skor sedang/tinggi, atau None.

    None = tidak ada narasi (skor rendah / belum ada data / API key kosong /
    dalam masa jeda / slot penuh / Gemini gagal). TIDAK PERNAH melempar
    exception: pemanggil tetap mengembalikan skor angka apa pun yang terjadi di sini.
    """
    if not lookup.has_data or lookup.risk_level not in _NARRATED_LEVELS:
        return None

    try:
        settings = get_settings()
        if not settings.gemini_api_key:
            logger.info("GEMINI_API_KEY belum diset, narasi skor risiko dilewati")
            return None
        facts = build_narrative_facts(lookup, settings)
    except Exception as exc:  # noqa: BLE001 - narasi opsional: kegagalan apa pun tidak boleh sampai ke endpoint
        logger.warning("Narasi skor risiko dilewati: %s", safe_error_summary(exc))
        return None

    api_key = settings.gemini_api_key
    return gemini_narration.gemini_narration_guard.run(
        facts, lambda: _invoke_narration(facts, api_key), clean_narrative
    )
