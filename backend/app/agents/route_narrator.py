"""Lapisan narasi Safe Route Advisor: Gemini MENJELASKAN hasil pemeriksaan rute.

Status rute (aman/waspada/berisiko tinggi) dan daftar area yang dihindari
SELALU berasal dari penilaian deterministik di `route_agent.py` (TC-RTE-001:
rute yang melintasi area berskor tinggi tidak boleh ditampilkan sebagai aman).
Modul ini hanya mengubah hasil itu jadi 1-2 kalimat Bahasa Indonesia yang
tenang dan netral (REQ-NF-141) — Gemini tidak pernah menilai atau mengubah status.

Narasi HANYA untuk rute waspada/berisiko tinggi, dan opsional: bila Gemini tidak
siap (API key kosong, 429, timeout, penuh) fungsi mengembalikan None dan hasil
rute tetap lengkap. Perlindungan kuota dipakai bersama narasi skor
(`gemini_narration.py`).

Data ke Gemini hanya agregat: status, skor tertinggi, jam, NAMA AREA tingkat
kecamatan dari pusat sel grid publik, jarak/durasi, dan cakupan data. TANPA teks
alamat yang diketik pengguna, koordinat, atau identitas apa pun (REQ-NF-120/121,
REQ-F-042).

KNOWN LIMITATION: isi narasi dijaga lewat prompt, bukan diverifikasi otomatis;
LLM masih bisa salah memparafrasekan fakta.
"""

import logging
from dataclasses import dataclass

from app.agents import gemini_narration
from app.agents.gemini_narration import clean_narrative
from app.agents.risk_agent import JELANG_RAMADAN, SELAMA_RAMADAN, TIME_BUCKET_HOURS
from app.core.config import get_settings
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

_NARRATED_ROUTE_LEVELS = frozenset({"waspada", "berisiko_tinggi"})

_SYSTEM_PROMPT = (
    "Kamu menulis ringkasan singkat untuk warga Yogyakarta tentang tingkat kerawanan sebuah "
    "RUTE perjalanan terhadap kejahatan jalanan (klitih). Hasil pemeriksaan sistem di bawah "
    "sudah FINAL; tugasmu hanya menjelaskannya dengan bahasa yang mudah dipahami.\n"
    "Aturan:\n"
    "- Tulis 1-2 kalimat Bahasa Indonesia yang tenang dan informatif, tidak sensasional, "
    "tidak menakut-nakuti.\n"
    "- Pakai HANYA fakta yang diberikan. Jangan menambah angka, nama jalan/tempat, kronologi "
    "kejadian, atau penyebab lain yang tidak ada di fakta.\n"
    "- Sebut status rute persis seperti yang diberikan; jangan menilai ulang atau mengubahnya.\n"
    "- Bila ada ruas jalan yang disarankan dihindari, sebut namanya persis seperti diberikan (nama jalan dan "
    "kecamatan). Jangan menyebut koordinat atau rincian kejadian individual. "
    "Boleh menyarankan mempertimbangkan waktu berangkat lain atau tetap waspada, tanpa "
    "menyebut jalan/jalur alternatif tertentu.\n"
    "- Sebut pengaruh musim (Ramadan) hanya bila ada di fakta; bila disebut, jelaskan bahwa skor area "
    "sudah disesuaikan dengan musim tersebut.\n"
    "- Bila cakupan data rendah (skor hanya tersedia untuk sebagian area yang dilintasi), "
    "sampaikan bahwa hasil terbatas pada data yang tersedia.\n"
    "- Jangan menyebut identitas atau ciri kelompok orang mana pun, jangan menjanjikan "
    "keamanan, dan jangan menyarankan tindakan main hakim sendiri.\n"
    "- Keluarkan hanya kalimat ringkasannya, tanpa judul, daftar, atau format markdown."
)
_HUMAN_TEMPLATE = "Fakta hasil pemeriksaan rute:\n{facts}\n\nTulis ringkasannya."


@dataclass(frozen=True)
class RouteNarrativeFacts:
    """Seluruh masukan narasi rute. Frozen/hashable: sekaligus jadi kunci cache."""

    route_level: str  # aman / waspada / berisiko_tinggi (keputusan deterministik)
    max_risk_score: float  # dibulatkan 1 desimal supaya cache tidak terlalu terpecah
    time_buckets: tuple[str, ...]  # bucket jam yang dilintasi, urut sepanjang rute
    avoid_places: tuple[str, ...]  # nama ruas jalan (+kecamatan) berisiko tinggi (tanpa duplikat)
    watch_places: tuple[str, ...]  # nama ruas jalan (+kecamatan) berisiko sedang (tanpa duplikat)
    distance_km: float
    duration_minutes: int
    areas_checked: int  # jumlah titik pemeriksaan di jalur
    areas_with_data: int  # di antaranya yang punya data kejadian di sekitarnya
    season: str | None = None  # JELANG_RAMADAN / SELAMA_RAMADAN / None pada tanggal berangkat


def _describe_season(season: str | None) -> str:
    if season == JELANG_RAMADAN:
        return "menjelang Ramadan; skor kerawanan area sudah dikali pengali musim"
    if season == SELAMA_RAMADAN:
        return "selama Ramadan; skor kerawanan area sudah dikali pengali musim"
    return "tidak ada pengaruh musim (jangan menyinggung musim atau Ramadan)"


def _describe_time_bucket(bucket: str) -> str:
    start_hour, end_hour = next((s, e) for name, s, e in TIME_BUCKET_HOURS if name == bucket)
    return f"{bucket.replace('_', ' ')} ({start_hour:02d}.00-{end_hour:02d}.00 WIB)"


def render_route_facts(facts: RouteNarrativeFacts) -> str:
    """Fakta sebagai daftar teks untuk prompt."""
    avoid = ", ".join(facts.avoid_places) if facts.avoid_places else "tidak ada"
    watch = ", ".join(facts.watch_places) if facts.watch_places else "tidak ada"
    return "\n".join(
        [
            f"- Status rute: {facts.route_level.replace('_', ' ')}",
            f"- Skor kerawanan tertinggi di sepanjang rute: {facts.max_risk_score:.1f} dari 10",
            f"- Rentang waktu perjalanan: {', lalu '.join(_describe_time_bucket(b) for b in facts.time_buckets)}",
            f"- Ruas jalan yang disarankan dihindari (berisiko tinggi): {avoid}",
            f"- Ruas jalan yang perlu diwaspadai (berisiko sedang): {watch}",
            f"- Jarak dan perkiraan durasi: {facts.distance_km:.1f} km, sekitar {facts.duration_minutes} menit",
            f"- Cakupan data: ada data kejadian di sekitar {facts.areas_with_data} dari {facts.areas_checked} titik pemeriksaan di jalur",
            f"- Musim pada tanggal berangkat: {_describe_season(facts.season)}",
        ]
    )


def _invoke_route_narration(facts: RouteNarrativeFacts, api_key: str) -> str:
    """Satu kali panggilan Gemini lewat chain LangChain bersama (gemini_narration).
    Exception dibiarkan naik ke NarrationGuard yang menanganinya."""
    chain = gemini_narration.build_narration_chain(_SYSTEM_PROMPT, _HUMAN_TEMPLATE, api_key)
    return chain.invoke({"facts": render_route_facts(facts)})


def generate_route_narrative(facts: RouteNarrativeFacts) -> str | None:
    """Ringkasan 1-2 kalimat untuk rute waspada/berisiko tinggi, atau None.

    None = tidak ada narasi (rute aman / API key kosong / masa jeda / slot penuh /
    Gemini gagal). TIDAK PERNAH melempar exception: hasil rute tetap dikembalikan.
    """
    if facts.route_level not in _NARRATED_ROUTE_LEVELS:
        return None

    try:
        api_key = get_settings().gemini_api_key
    except Exception as exc:  # noqa: BLE001 - narasi opsional: kegagalan apa pun tidak boleh sampai ke endpoint
        logger.warning("Narasi rute dilewati: %s", safe_error_summary(exc))
        return None
    if not api_key:
        logger.info("GEMINI_API_KEY belum diset, narasi rute dilewati")
        return None

    return gemini_narration.gemini_narration_guard.run(
        facts, lambda: _invoke_route_narration(facts, api_key), clean_narrative
    )
