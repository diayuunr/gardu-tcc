"""Verification & Clustering Agent — versi MVP (Gardu).

Modul terpisah sesuai CLAUDE.md aturan #3 (jangan digabung dengan Risk
Prediction Agent atau Safe Route Advisor).

KETERBATASAN VERSI INI (jujur, bukan pura-pura lengkap):
- Bagian A (entity extraction) memanggil Gemini API sungguhan (google-genai,
  model gemini-3.6-flash, JSON mode). Belum ada evaluasi akurasi ekstraksi
  di luar smoke test manual/otomatis di backend/tests/test_verification_agent.py.
- Bagian B (clustering) MASIH heuristik lokasi (substring match,
  case-insensitive) + kategori waktu, BUKAN vector similarity search.
  Lihat TODO(REQ-F-011) di fungsi `_cluster`.
- Kolom `embedding` di tabel reports SENGAJA TIDAK diisi (tetap NULL) di
  versi ini — tidak ada perhitungan embedding sungguhan, jadi tidak
  dipura-purakan ada.
- docs/contracts.md untuk tabel `reports` TIDAK punya kolom `time_period`,
  `incident_type`, atau `cluster_id`. Field-field itu tetap dikembalikan di
  response API sesuai kontrak /agents/verify, tapi TIDAK dipersist ke tabel
  reports (cuma `location` & `status` yang disimpan — lihat
  update_report_verification() di backend/db/queries.py). Kalau field ini
  perlu disimpan permanen, itu perubahan skema yang wajib didiskusikan tim
  dulu, bukan ditambahkan sepihak di sini.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from google import genai
from google.genai import types

from backend.db.queries import get_recent_reports, get_report_by_id

MODEL = "gemini-3.6-flash"

DUPLICATE_WINDOW_HOURS = 24
DUPLICATE_FLAG_THRESHOLD = 3

_TIME_CATEGORIES = ("dini_hari", "pagi", "siang", "sore", "malam")

SYSTEM_PROMPT = (
    "Kamu adalah entity extractor untuk laporan kejadian klitih/kejahatan "
    "jalanan di Yogyakarta. Extract location, time, dan incident_type dari "
    "teks laporan. Kalau lokasi atau jenis kejadian tidak disebutkan, isi "
    'dengan string kosong "". Untuk time, tebak kategori paling masuk akal '
    "dari konteks (mis. \"jam 2 pagi\" -> dini_hari)."
)

# response_schema OpenAPI-style: memaksa Gemini taat ke 5 kategori waktu
# lewat enum, bukan cuma diminta lewat teks prompt — soalnya JSON mode
# (response_mime_type) doang cuma menjamin valid JSON, bukan menjamin isi
# field "time" sesuai kontrak (sempat kejadian nyata: Gemini balas "02:00"
# alih-alih "dini_hari" waktu response_schema belum dipakai).
RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "location": {"type": "STRING"},
        "time": {"type": "STRING", "enum": list(_TIME_CATEGORIES)},
        "incident_type": {"type": "STRING"},
    },
    "required": ["location", "time", "incident_type"],
}


class VerificationError(Exception):
    """Dilempar kalau Verification Agent gagal total (API AI gagal, atau
    responsnya tidak bisa dipakai setelah retry). Tidak pernah silent fail
    dan tidak pernah mengembalikan data ngasal."""


_client: Optional[genai.Client] = None


def _get_gemini_client() -> genai.Client:
    """Lazy singleton — sengaja TIDAK dicek saat modul di-import, supaya
    endpoint lain (risk, reports) tetap jalan walau GEMINI_API_KEY belum
    di-set. Baru gagal saat Verification Agent benar-benar dipanggil."""
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise VerificationError(
            "GEMINI_API_KEY belum di-set. Copy .env.example ke .env lalu "
            "isi nilainya sebelum memanggil Verification Agent. Ambil API "
            "key gratis di https://aistudio.google.com/apikey"
        )

    _client = genai.Client(api_key=api_key)
    return _client


def _call_gemini(text: str) -> str:
    client = _get_gemini_client()
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
            ),
        )
    except Exception as exc:
        raise VerificationError(f"Panggilan Gemini API gagal: {exc}") from exc

    return response.text


def _parse_entities(raw: str) -> dict:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError(f"Response Gemini bukan JSON object: {raw!r}")

    for key in ("location", "time", "incident_type"):
        if key not in parsed:
            raise ValueError(f"Response Gemini tidak punya field '{key}': {raw!r}")

    if parsed["time"] not in _TIME_CATEGORIES:
        raise ValueError(
            f"time {parsed['time']!r} bukan salah satu dari {_TIME_CATEGORIES}: {raw!r}"
        )

    return parsed


def _extract_entities(text: str) -> dict:
    """Panggil Gemini, parse JSON. Retry sekali kalau gagal (API error
    maupun parse error), baru raise VerificationError yang jelas — tidak
    pernah silent fail atau mengembalikan data ngasal."""
    last_error: Optional[Exception] = None
    last_raw: Optional[str] = None

    for _ in range(2):
        try:
            raw = _call_gemini(text)
            last_raw = raw
            return _parse_entities(raw)
        except Exception as exc:  # noqa: BLE001 - sengaja luas, semua jalur gagal masuk retry
            last_error = exc

    raise VerificationError(
        "Entity extraction gagal setelah 1x retry. "
        f"Error terakhir: {last_error!r}. Raw response terakhir: {last_raw!r}."
    ) from last_error


WIB = timezone(timedelta(hours=7))


def _time_bucket_from_reported_at(reported_at: Optional[str]) -> Optional[str]:
    """Heuristik: turunkan kategori waktu dari `reported_at` laporan,
    karena tabel reports tidak punya kolom time_period tersendiri.
    Jam dihitung dalam WIB (UTC+7): database mengembalikan waktu dalam UTC."""
    if not reported_at:
        return None
    # Python 3.9 hanya menerima pecahan detik 3 atau 6 digit; samakan jadi 6 digit.
    teks = re.sub(
        r"\.(\d+)",
        lambda m: "." + m.group(1).ljust(6, "0")[:6],
        reported_at.replace("Z", "+00:00"),
    )
    try:
        dt = datetime.fromisoformat(teks)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(WIB)

    hour = dt.hour
    if 0 <= hour < 5:
        return "dini_hari"
    if 5 <= hour < 11:
        return "pagi"
    if 11 <= hour < 15:
        return "siang"
    if 15 <= hour < 18:
        return "sore"
    return "malam"


def _location_matches(a: str, b: str) -> bool:
    a_norm = (a or "").strip().lower()
    b_norm = (b or "").strip().lower()
    if not a_norm or not b_norm:
        return False
    return a_norm in b_norm or b_norm in a_norm


# TODO(REQ-F-011): Ini masih heuristik lokasi+waktu, BUKAN vector
# similarity search yang sesungguhnya. Upgrade ke pgvector cosine
# similarity kalau ada waktu tambahan setelah submission.
def _cluster(
    report_id: str,
    location: str,
    time_category: str,
    kecamatan_kode: Optional[str] = None,
):
    """Return (cluster_id, flagged) di antara reports yang dibuat dalam
    DUPLICATE_WINDOW_HOURS jam terakhir.

    Dua laporan dianggap serupa kalau kategori jamnya sama DAN wilayahnya sama:
    kecamatan_kode yang sama bila kedua laporan punya kode; kalau salah satunya
    tidak punya, jatuh ke pencocokan teks lokasi seperti sebelumnya."""
    since = datetime.now(timezone.utc) - timedelta(hours=DUPLICATE_WINDOW_HOURS)
    recent_reports = get_recent_reports(since)

    matches = []
    for row in recent_reports:
        if row["id"] == report_id:
            continue
        if _time_bucket_from_reported_at(row.get("reported_at")) != time_category:
            continue
        if kecamatan_kode and row.get("kecamatan_kode"):
            sama_wilayah = row["kecamatan_kode"] == kecamatan_kode
        else:
            sama_wilayah = _location_matches(location, row.get("location") or "")
        if sama_wilayah:
            matches.append(row)

    cluster_id = matches[0]["id"] if matches else None
    flagged = len(matches) > DUPLICATE_FLAG_THRESHOLD

    return cluster_id, flagged


def verify_report(report_id: str, text: str, report: Optional[dict] = None) -> dict:
    """Sesuai docs/contracts.md — POST /agents/verify.

    Response: { "location", "time", "incident_type", "cluster_id", "flagged" }

    `report` (baris dari tabel reports) boleh diberikan supaya tidak dibaca dua kali;
    kalau kosong, dibaca di sini.
    """
    entities = _extract_entities(text)

    if report is None:
        report = get_report_by_id(report_id)
    report = report or {}

    kecamatan_kode = report.get("kecamatan_kode")
    # Jam laporan ini diambil dari reported_at (cara yang sama dengan laporan lain);
    # tebakan Gemini hanya cadangan kalau reported_at tidak ada.
    time_category = _time_bucket_from_reported_at(report.get("reported_at")) or entities["time"]
    # Laporan berkode: pencocokan lewat kode, teks lokasi tidak dipakai.
    location = entities["location"] if not kecamatan_kode else (report.get("location") or "")

    cluster_id, flagged = _cluster(report_id, location, time_category, kecamatan_kode)

    return {
        "location": entities["location"],
        "time": entities["time"],
        "incident_type": entities["incident_type"],
        "cluster_id": cluster_id,
        "flagged": flagged,
    }
