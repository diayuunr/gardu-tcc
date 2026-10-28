import logging
import re
import time
from datetime import datetime, timedelta

from google.api_core.exceptions import TooManyRequests
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, ValidationError
from supabase import Client

from app.agents.embedding_service import generate_embedding
from app.agents.risk_agent import refresh_risk_scores_safely
from app.core.config import Settings, get_settings
from app.core.db_retry import execute_with_retry
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.core.timeutil import WIB, to_wib

logger = logging.getLogger(__name__)

STATUS_PENDING = "menunggu_verifikasi"
STATUS_DUPLICATE = "ditandai_duplikat"
STATUS_HOAX = "ditandai_hoaks"
# Laporan berstatus ini TIDAK boleh dianggap bukti independen: tidak jadi kecocokan
# klaster dan tidak pernah diberi incident_id.
FLAGGED_STATUSES = frozenset({STATUS_DUPLICATE, STATUS_HOAX})

# Kode alasan penandaan (disimpan di kolom `flagged_reason`). SENGAJA kode tetap,
# bukan kutipan teks laporan: moderator melihat "kenapa", tanpa teks laporan masuk log/kolom lain.
REASON_NO_LETTERS = "tanpa_huruf"
REASON_REPEATED_CHARS = "karakter_berulang"
REASON_REPEATED_WORD = "kata_berulang"
REASON_SIMILAR_REPORT = "mirip_laporan_lain"

# Verification Agent full pakai Gemini (embedding + klasifikasi), bukan
# campuran provider — satu API key (GEMINI_API_KEY) cukup untuk seluruh
# agent ini. "flash-lite" dipilih karena tugasnya cuma klasifikasi
# kategori singkat, tidak butuh model besar; alias "-latest" (bukan versi
# ter-pin tanggal) dipakai supaya tidak kena masalah retirement seperti
# yang terjadi pada model embedding text-embedding-004 sebelumnya.
EXTRACTION_MODEL = "models/gemini-flash-lite-latest"

_EXTRACTION_SYSTEM_PROMPT = (
    "Kamu membantu sistem kesadaran komunitas warga Yogyakarta mengategorikan "
    "laporan indikasi kejahatan jalanan (klitih). Baca deskripsi kejadian dari "
    "warga, lalu tentukan HANYA kategori jenis kejadiannya secara singkat. "
    "JANGAN menyebut ulang nama orang, ciri fisik, atau identitas siapa pun "
    "(pelapor maupun terduga pelaku) dalam output — cukup kategori kejadian."
)


# Skema output terstruktur untuk ekstraksi entitas (REQ-F-010).
#
# Lokasi & waktu SUDAH berupa field terstruktur dari form Lapor Kejadian
# (REQ-F-002/003), jadi tidak perlu diekstrak ulang dari teks bebas —
# satu-satunya hal yang genuinely perlu inferensi AI dari teks laporan
# adalah jenis kejadian, makanya skema ini cuma punya satu field.
#
# PENTING: docstring class ini DIKIRIM ke Gemini sebagai deskripsi tool-nya.
# Jangan isi dengan catatan developer — dulu docstring berisi kata
# "`description`" dan bikin model ~37% kali salah mengisi argumen bernama
# `description` (bukan `incident_type`) -> validasi gagal -> hasil NULL.
# Catatan developer taruh di komentar seperti ini, bukan di docstring.
class ExtractedEntities(BaseModel):
    """Kategori jenis kejadian dari sebuah laporan warga."""

    incident_type: str = Field(
        description=(
            "Kategori singkat jenis kejadian dalam Bahasa Indonesia, contoh: "
            "'penyerangan', 'pengeroyokan', 'percobaan begal', 'pengrusakan', "
            "'kejadian mencurigakan'. Pakai 'lainnya' kalau tidak jelas."
        )
    )


# Free tier Gemini dibatasi 15 request/menit per model. Retry bawaan
# langchain-google-genai (versi terpasang) hardcode 1x retry setelah ~2 detik,
# terlalu singkat untuk limit per-menit — jadi 429 ditangani sendiri di sini
# dengan menunggu sesuai `retry_delay` yang disarankan server.
_RATE_LIMIT_MAX_RETRIES = 2
_RATE_LIMIT_DEFAULT_BACKOFF_SECONDS = 5.0  # dipakai kalau server tidak menyebut retry_delay
# Limit per-menit Gemini meminta tunggu sampai ~60 dtk (teramati 25-49 dtk di
# tes nyata; batas awal 30 dtk terbukti terlalu kecil -> semua langsung
# menyerah). Permintaan lebih lama dari ini (mis. kuota harian habis = jam)
# -> menyerah, supaya worker threadpool tidak tertahan sia-sia.
_RATE_LIMIT_MAX_WAIT_SECONDS = 60.0
_RETRY_DELAY_PATTERN = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)


def _summarize_error(exc: Exception) -> str:
    """Ringkas pesan error jadi satu baris pendek (pesan 429 Google multi-baris & panjang)."""
    return " ".join(str(exc).split())[:300]


def _summarize_validation_error(exc: ValidationError) -> str:
    """Ringkas ValidationError jadi 'field: tipe_error' SAJA.

    Sengaja TIDAK memakai str(exc)/traceback: pesan bawaan Pydantic memuat
    `input_value` = potongan teks laporan warga, yang bisa berisi data
    pribadi dan tidak boleh masuk log server.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or '(root)'}: {err['type']}"
        for err in exc.errors(include_input=False, include_url=False)
    )


def _rate_limit_wait_seconds(exc: Exception, attempt: int) -> float | None:
    """Hitung lama tunggu sebelum retry setelah 429; None = jangan retry.

    `attempt` mulai dari 0. Pakai retry_delay dari server kalau ada (+1 dtk
    margin), kalau tidak pakai exponential backoff (5s, 10s).
    """
    match = _RETRY_DELAY_PATTERN.search(str(exc))
    if match:
        wait = float(match.group(1)) + 1.0
    else:
        wait = _RATE_LIMIT_DEFAULT_BACKOFF_SECONDS * (2**attempt)
    return wait if wait <= _RATE_LIMIT_MAX_WAIT_SECONDS else None


def _invoke_extraction(description: str, api_key: str) -> ExtractedEntities | None:
    """Satu kali panggilan Gemini (structured output). Exception dibiarkan naik
    ke pemanggil supaya bisa dibedakan rate limit vs error lain."""
    llm = ChatGoogleGenerativeAI(
        model=EXTRACTION_MODEL,
        google_api_key=api_key,
        timeout=10,
    )
    structured_llm = llm.with_structured_output(ExtractedEntities)
    return structured_llm.invoke(
        [
            ("system", _EXTRACTION_SYSTEM_PROMPT),
            ("human", description),
        ]
    )


def extract_incident_type(description: str) -> str | None:
    """Klasifikasikan jenis kejadian dari teks laporan bebas (REQ-F-010).

    Tidak pernah melempar exception: kalau GEMINI_API_KEY belum diset atau
    panggilan API gagal, return None (REQ-NF-110 — laporan tetap tersimpan
    tanpa extracted_incident_type, bisa diproses ulang nanti). Setiap
    kegagalan di-log eksplisit, tidak ada yang diam-diam jadi None:
    - 429 rate limit: retry maksimal 2x sesuai retry_delay dari server
    - error lain (auth, timeout, dll): tidak di-retry, di-log dengan traceback
    - hasil kosong/tidak terparse (mis. diblokir safety filter): di-log
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.info("GEMINI_API_KEY belum diset, lewati ekstraksi entitas")
        return None

    for attempt in range(_RATE_LIMIT_MAX_RETRIES + 1):
        try:
            result = _invoke_extraction(description, settings.gemini_api_key)
        except TooManyRequests as exc:
            wait_seconds = _rate_limit_wait_seconds(exc, attempt)
            if attempt >= _RATE_LIMIT_MAX_RETRIES or wait_seconds is None:
                logger.error(
                    "Ekstraksi jenis kejadian GAGAL: rate limit Gemini (429), menyerah setelah %d percobaan: %s",
                    attempt + 1,
                    _summarize_error(exc),
                )
                return None
            logger.warning(
                "Rate limit Gemini (429) saat ekstraksi, retry ke-%d dalam %.0f detik: %s",
                attempt + 1,
                wait_seconds,
                _summarize_error(exc),
            )
            time.sleep(wait_seconds)
            continue
        except ValidationError as exc:
            # Model kadang mengisi argumen tool dengan key yang salah. Log HANYA
            # nama field + tipe error, tanpa traceback/input_value (lihat
            # _summarize_validation_error) supaya teks laporan tidak bocor ke log.
            logger.error(
                "Ekstraksi jenis kejadian GAGAL: output Gemini tidak sesuai skema (%s)",
                _summarize_validation_error(exc),
            )
            return None
        except Exception as exc:  # noqa: BLE001 - semua error panggilan AI wajib ditangani eksplisit
            # Tanpa exc_info/str(exc): pesan & traceback library bisa memuat
            # teks laporan (lihat app/core/safe_log.py).
            logger.error("Ekstraksi jenis kejadian GAGAL: %s", safe_error_summary(exc))
            return None

        if result is None:
            logger.warning(
                "Ekstraksi jenis kejadian: Gemini mengembalikan hasil kosong/tidak terparse "
                "(kemungkinan diblokir safety filter atau output tidak sesuai skema)"
            )
            return None

        return result.incident_type


def assess_report_text(description: str, settings: Settings | None = None) -> str | None:
    """Heuristik penanda laporan tidak wajar (REQ-F-012) — kode alasan, atau None kalau wajar.

    DETERMINISTIK dan KONSERVATIF: hanya menangkap teks yang jelas sampah, dengan
    syarat yang mustahil dipenuhi kalimat laporan sungguhan. Tidak memakai LLM
    (hasil harus reprodusibel) dan tidak menilai isi/kebenaran cerita. Aturan
    (setelah teks diubah ke huruf kecil dan hanya huruf/angka yang dihitung):

    - `tanpa_huruf`       : tidak ada satu huruf pun (mis. "1234567890", "!!!!!!!!!!").
    - `karakter_berulang` : < `verification_hoax_min_distinct_chars` (default 4) huruf/angka
                            BERBEDA (mis. "aaaaaaaaaa", "hahahahaha", "asdasdasdasd").
    - `kata_berulang`     : satu kata yang sama diulang >= `verification_hoax_repeat_min_words`
                            (default 4) kali tanpa kata lain (mis. "tolong tolong tolong tolong").

    Sengaja TIDAK dipakai: koordinat di luar wilayah. Geocoding sudah dibatasi ke DIY,
    sedangkan koordinat manual di luar DIY jarang dan menandainya sebagai hoaks berisiko
    menyalahtandai laporan sah dari luar kota. Laporan yang lolos tetap dinilai moderator.
    Kegagalan di sini bukan hukuman final: status `ditandai_hoaks` bisa ditinjau moderator.
    """
    settings = settings or get_settings()
    normalized = [char for char in description.casefold() if char.isalnum()]
    if not any(char.isalpha() for char in normalized):
        return REASON_NO_LETTERS
    if len(set(normalized)) < settings.verification_hoax_min_distinct_chars:
        return REASON_REPEATED_CHARS

    words = [word for word in re.split(r"[^\w]+", description.casefold()) if word]
    if len(words) >= settings.verification_hoax_repeat_min_words and len(set(words)) == 1:
        return REASON_REPEATED_WORD
    return None


def _fetch_report(supabase: Client, report_id: str) -> dict | None:
    response = execute_with_retry(
        supabase.table("reports")
        .select(
            "id,description,location_text,latitude,longitude,occurred_at,incident_id,status,extracted_incident_type"
        )
        .eq("id", report_id)
        .limit(1)
    )
    return response.data[0] if response.data else None


def _flag_report(supabase: Client, report_id: str, status: str, reason: str) -> None:
    """Tandai laporan. Status ditulis DULU (penting); alasan terpisah dan best-effort
    supaya kolom `flagged_reason` yang belum dimigrasi tidak menggagalkan penandaan."""
    execute_with_retry(supabase.table("reports").update({"status": status}).eq("id", report_id))
    try:
        execute_with_retry(supabase.table("reports").update({"flagged_reason": reason}).eq("id", report_id))
    except Exception as exc:  # noqa: BLE001 - alasan hanya pelengkap bagi moderator
        logger.warning("Alasan penandaan tidak tersimpan (kolom flagged_reason sudah dimigrasi?): %s", safe_error_summary(exc))


def _find_similar_reports(
    supabase: Client,
    *,
    embedding: list[float],
    exclude_report_id: str,
    occurred_at: datetime,
    latitude: float | None,
    longitude: float | None,
) -> list[dict]:
    """Panggil RPC `match_similar_reports` (REQ-F-011)."""
    settings = get_settings()
    window_start = occurred_at - timedelta(hours=settings.verification_time_window_hours)
    window_end = occurred_at + timedelta(hours=settings.verification_time_window_hours)

    response = execute_with_retry(
        supabase.rpc(
            "match_similar_reports",
            {
                "query_embedding": embedding,
                "exclude_report_id": exclude_report_id,
                "time_window_start": window_start.isoformat(),
                "time_window_end": window_end.isoformat(),
                "query_latitude": latitude,
                "query_longitude": longitude,
                "max_distance_degrees": settings.verification_geo_bbox_degrees,
                "similarity_threshold": settings.verification_similarity_threshold,
                "match_limit": 5,
            },
        )
    )
    return response.data or []


def _fetch_match_details(supabase: Client, match_ids: list[str]) -> dict[str, dict]:
    """Status & koordinat laporan-laporan yang cocok (RPC hanya mengembalikan id/incident/similarity)."""
    if not match_ids:
        return {}
    response = execute_with_retry(
        supabase.table("reports").select("id,status,latitude,longitude").in_("id", match_ids)
    )
    return {row["id"]: row for row in response.data or []}


def _drop_flagged_matches(supabase: Client, matches: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Buang kecocokan berstatus duplikat/hoaks (pertahanan KEDUA setelah filter di
    fungsi SQL `match_similar_reports`, yang mungkin belum dimigrasi).

    Return (kecocokan yang sah, detail {id: baris} semua kecocokan). Kecocokan yang
    statusnya tidak diketahui (baris tak ditemukan) dipertahankan — hanya yang
    TERBUKTI ditandai yang dibuang.
    """
    details = _fetch_match_details(supabase, [m["id"] for m in matches])

    def is_flagged(match: dict) -> bool:
        status = match.get("status") or details.get(match["id"], {}).get("status")
        return status in FLAGGED_STATUSES

    return [m for m in matches if not is_flagged(m)], details


def _coordinates_of(row: dict | None) -> tuple[float, float] | None:
    if row is None or row.get("latitude") is None or row.get("longitude") is None:
        return None
    return float(row["latitude"]), float(row["longitude"])


def _first_coordinates(sources: list[dict | None]) -> tuple[float, float] | None:
    """Koordinat pertama yang lengkap; urutan `sources` = prioritas (pembuat insiden dulu)."""
    return next((c for c in (_coordinates_of(row) for row in sources) if c is not None), None)


def _create_incident(
    supabase: Client, report: dict, incident_type: str | None, coordinate_sources: list[dict | None] | None = None
) -> str:
    """Buat insiden dari `report`. Koordinat: laporan pembuat dulu, lalu laporan lain di
    klaster (`coordinate_sources`) yang punya koordinat — insiden tanpa koordinat tidak
    ikut skor kerawanan, jadi sebisa mungkin jangan dibiarkan kosong."""
    coordinates = _first_coordinates([report, *(coordinate_sources or [])])
    record = {
        "location_text": report["location_text"],
        "latitude": coordinates[0] if coordinates else None,
        "longitude": coordinates[1] if coordinates else None,
        "incident_time": report["occurred_at"],
        "incident_type": incident_type,
        "is_seed_data": False,
    }
    response = execute_with_retry(supabase.table("incidents").insert(record))
    return response.data[0]["id"]


def _fill_incident_coordinates(
    supabase: Client, incident_id: str, coordinate_sources: list[dict | None]
) -> bool:
    """Isi koordinat insiden yang masih kosong dari laporan anggota klaster.
    Tidak pernah menimpa koordinat yang sudah ada. Return True kalau diperbarui."""
    response = execute_with_retry(
        supabase.table("incidents").select("id,latitude,longitude").eq("id", incident_id).limit(1)
    )
    if not response.data or _coordinates_of(response.data[0]) is not None:
        return False
    coordinates = _first_coordinates(coordinate_sources)
    if coordinates is None:
        return False
    execute_with_retry(
        supabase.table("incidents")
        .update({"latitude": coordinates[0], "longitude": coordinates[1]})
        .eq("id", incident_id)
    )
    return True


def _parse_created_at(raw: object) -> datetime:
    try:
        return to_wib(datetime.fromisoformat(str(raw)))
    except ValueError:
        return datetime.max.replace(tzinfo=WIB)  # tak terbaca = dianggap paling baru


def _merge_into_oldest_incident(supabase: Client, incident_ids: list[str]) -> str | None:
    """Gabungkan semua insiden komunitas yang dirujuk kecocokan ke insiden TERTUA.

    Kenapa tertua: ia titik awal klaster dan paling mungkin sudah terverifikasi/dirujuk
    sistem lain; yang lebih baru adalah pecahan yang ternyata satu kejadian. Laporan
    anggota dipindahkan lalu insiden kosongnya dihapus — kalau dibiarkan, insiden
    terverifikasi tanpa laporan akan terus dihitung di skor kerawanan (hitungan ganda).
    Insiden seed data TIDAK pernah digabung/dihapus. Return id insiden tujuan, atau
    None kalau tidak ada satu pun yang ditemukan (id usang)."""
    unique_ids = list(dict.fromkeys(incident_ids))
    response = execute_with_retry(
        supabase.table("incidents").select("id,created_at,is_seed_data").in_("id", unique_ids)
    )
    candidates = [row for row in response.data or [] if not row.get("is_seed_data")]
    if not candidates:
        return None

    target_row = min(candidates, key=lambda row: (_parse_created_at(row.get("created_at")), str(row["id"])))
    target_id = target_row["id"]
    for row in candidates:
        if row["id"] == target_id:
            continue
        execute_with_retry(
            supabase.table("reports").update({"incident_id": target_id}).eq("incident_id", row["id"])
        )
        execute_with_retry(supabase.table("incidents").delete().eq("id", row["id"]))
        logger.info("Insiden %s digabung ke insiden tertua %s", row["id"], target_id)
    return target_id


def _count_incident_reports(supabase: Client, incident_id: str) -> int:
    """Hitung laporan INDEPENDEN dalam satu klaster (REQ-F-013).

    Secara struktural laporan yang ditandai duplikat/hoaks memang tidak
    pernah diberi incident_id (lihat cabang duplikat di
    process_report_verification), tapi filter status di sini tetap
    dipasang eksplisit — supaya definisi "independen" tidak diam-diam
    bergantung pada invariant di tempat lain yang bisa berubah nanti.
    """
    response = execute_with_retry(
        supabase.table("reports")
        .select("id", count="exact")
        .eq("incident_id", incident_id)
        .neq("status", "ditandai_duplikat")
        .neq("status", "ditandai_hoaks")
    )
    return response.count or 0


def _promote_incident_if_verified(supabase: Client, incident_id: str) -> bool:
    """REQ-F-013: promosikan status jadi 'terverifikasi' begitu klaster
    didukung >=2 laporan independen. Laporan yang sudah ditandai
    duplikat/hoaks TIDAK ikut dipromosikan (bukan bukti independen).

    Return True kalau insiden berstatus terverifikasi (dipromosikan barusan
    atau sudah sebelumnya), supaya pemanggil bisa memicu pembaruan skor risiko.
    """
    member_count = _count_incident_reports(supabase, incident_id)
    if member_count < 2:
        return False

    execute_with_retry(
        supabase.table("reports")
        .update({"status": "terverifikasi"})
        .eq("incident_id", incident_id)
        .neq("status", "ditandai_duplikat")
        .neq("status", "ditandai_hoaks")
    )
    execute_with_retry(supabase.table("incidents").update({"status": "terverifikasi"}).eq("id", incident_id))
    logger.info("Insiden %s dipromosikan jadi terverifikasi (%d laporan)", incident_id, member_count)
    return True


def process_report_verification(report_id: str) -> None:
    """Entry point Report Verification & Clustering Agent (REQ-F-010..014).

    Dipanggil sebagai FastAPI BackgroundTask setelah POST /reports berhasil
    (lihat app/api/reports.py) dan oleh skrip reprocessing — TIDAK memblokir respons
    submit laporan, sesuai REQ-NF-100 (konfirmasi cepat, di luar waktu proses AI)
    dan REQ-NF-102 (proses AI di latar belakang).

    Alur: periksa kewajaran teks (heuristik, tanpa AI) -> ekstrak jenis kejadian (LLM)
    -> buat embedding -> cari laporan mirip dalam rentang waktu/lokasi berdekatan
    (pgvector) -> gabung jadi klaster / tandai duplikat / promosikan terverifikasi.

    IDEMPOTEN (aman dijalankan ulang untuk laporan yang sama): laporan yang statusnya
    sudah bukan `menunggu_verifikasi` dilewati; laporan yang sudah punya `incident_id`
    hanya dilengkapi jenis kejadiannya, TIDAK diklasterkan lagi (tidak membuat
    insiden ganda); jenis kejadian yang sudah ada tidak diminta ulang ke Gemini.

    SELURUH fungsi dibungkus try/except paling luar: kegagalan apa pun di
    sini TIDAK BOLEH menghapus/merusak laporan mentah yang sudah tersimpan
    (REQ-NF-110). Laporan yang gagal diproses cukup tetap berstatus
    'menunggu_verifikasi' menunggu proses ulang (`python -m app.scripts.reprocess_reports`).
    """
    try:
        supabase = get_supabase()
        report = _fetch_report(supabase, report_id)
        if report is None:
            logger.warning("Laporan tidak ditemukan, verifikasi dibatalkan: %s", report_id)
            return
        if report.get("status") != STATUS_PENDING:
            logger.info("Laporan %s berstatus %s, verifikasi dilewati", report_id, report.get("status"))
            return

        settings = get_settings()
        reason = assess_report_text(report["description"], settings)
        if reason is not None:
            # REQ-F-012: teks jelas tidak wajar -> tandai untuk moderator, jangan buang
            # token AI/embedding dan jangan jadikan insiden. Log hanya kode alasan.
            _flag_report(supabase, report_id, STATUS_HOAX, reason)
            logger.info("Laporan %s ditandai hoaks (alasan=%s)", report_id, reason)
            return

        incident_type = report.get("extracted_incident_type") or extract_incident_type(report["description"])
        type_is_new = incident_type is not None and not report.get("extracted_incident_type")

        if report.get("incident_id"):
            # Sudah diklasterkan sebelumnya (proses ulang): cukup lengkapi jenis kejadian.
            if type_is_new:
                execute_with_retry(
                    supabase.table("reports").update({"extracted_incident_type": incident_type}).eq("id", report_id)
                )
            logger.info("Laporan %s sudah diklasterkan, klasterisasi dilewati", report_id)
            return

        embedding = generate_embedding(report["description"])

        update_fields: dict = {}
        if type_is_new:
            update_fields["extracted_incident_type"] = incident_type
        if embedding is not None:
            update_fields["embedding"] = embedding
        if update_fields:
            execute_with_retry(supabase.table("reports").update(update_fields).eq("id", report_id))

        if embedding is None:
            logger.info("Embedding gagal dibuat, clustering dilewati untuk laporan %s", report_id)
            return

        occurred_at = to_wib(datetime.fromisoformat(report["occurred_at"]))
        raw_matches = _find_similar_reports(
            supabase,
            embedding=embedding,
            exclude_report_id=report_id,
            occurred_at=occurred_at,
            latitude=report.get("latitude"),
            longitude=report.get("longitude"),
        )
        matches, details = _drop_flagged_matches(supabase, raw_matches)

        duplicate_match = next(
            (m for m in matches if m["similarity"] >= settings.verification_duplicate_threshold),
            None,
        )
        if duplicate_match is not None:
            # REQ-F-012: teks nyaris identik dalam rentang waktu/lokasi
            # berdekatan -> kemungkinan duplikat, tandai untuk ditinjau
            # moderator, JANGAN otomatis dianggap bukti independen.
            _flag_report(supabase, report_id, STATUS_DUPLICATE, REASON_SIMILAR_REPORT)
            logger.info(
                "Laporan %s ditandai duplikat (mirip %s, similarity=%.3f)",
                report_id,
                duplicate_match["id"],
                duplicate_match["similarity"],
            )
            return

        if not matches:
            # Belum ada korroborasi -> tetap buat insiden (klaster 1 anggota)
            # supaya Risk Prediction Agent (modul lain) punya satu sumber
            # data seragam (`incidents`), status laporan tetap menunggu.
            incident_id = _create_incident(supabase, report, incident_type)
            execute_with_retry(supabase.table("reports").update({"incident_id": incident_id}).eq("id", report_id))
            logger.info("Laporan %s jadi insiden baru (belum ada korroborasi): %s", report_id, incident_id)
            return

        # Sumber koordinat klaster: laporan ini dulu, lalu laporan-laporan yang cocok.
        coordinate_sources = [report, *(details.get(m["id"]) for m in matches)]
        linked_ids = [m["incident_id"] for m in matches if m["incident_id"]]
        incident_id = _merge_into_oldest_incident(supabase, linked_ids) if linked_ids else None
        if incident_id is None:
            incident_id = _create_incident(supabase, report, incident_type, coordinate_sources)
        else:
            _fill_incident_coordinates(supabase, incident_id, coordinate_sources)

        for match in matches:
            if match["incident_id"] != incident_id:
                execute_with_retry(
                    supabase.table("reports").update({"incident_id": incident_id}).eq("id", match["id"])
                )
        execute_with_retry(supabase.table("reports").update({"incident_id": incident_id}).eq("id", report_id))

        if _promote_incident_if_verified(supabase, incident_id):
            # Diagram sekuens SRS (fig4) langkah 5-6: insiden terverifikasi ->
            # Risk Prediction Agent memperbarui skor risiko (REQ-F-022).
            # Tidak pernah melempar exception, jadi tidak bisa mengganggu verifikasi.
            refresh_risk_scores_safely()

    except Exception as exc:  # noqa: BLE001 - kegagalan verifikasi TIDAK BOLEH merusak laporan mentah (REQ-NF-110)
        # Sengaja BUKAN logger.exception: traceback + pesan error database/LLM
        # bisa memuat isi baris/teks laporan. safe_error_summary tetap memberi
        # tipe error + file:baris asal error untuk keperluan debug.
        logger.error(
            "Verifikasi laporan %s gagal total, laporan mentah tetap tersimpan: %s",
            report_id,
            safe_error_summary(exc),
        )
