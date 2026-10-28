import logging
import os
import traceback

import httpx
from google.api_core.exceptions import GoogleAPICallError
from supabase import PostgrestAPIError


class _DropLibraryRetryLogs(logging.Filter):
    """Buang log 'Retrying <fn> in N seconds as it raised <Tipe>: <pesan>'.

    Log itu ditulis pustaka langchain-google-genai sendiri (tenacity
    `before_sleep_log`, chat_models.py) pada SETIAP retry internal, memuat
    pesan error MENTAH — bisa berisi isi request/teks laporan. Kita tidak bisa
    mengubah kode pustaka, jadi difilter di sini. Sengaja bukan menaikkan level
    logger ke ERROR: warning lain milik pustaka (mis. 'Gemini produced an empty
    response ... Feedback: ...', alasan blokir safety filter) tetap berguna dan
    tidak memuat teks laporan.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith("Retrying ")


def silence_library_retry_logs() -> None:
    """Pasang _DropLibraryRetryLogs di logger pustaka (aman dipanggil berulang)."""
    library_logger = logging.getLogger("langchain_google_genai.chat_models")
    if not any(isinstance(f, _DropLibraryRetryLogs) for f in library_logger.filters):
        library_logger.addFilter(_DropLibraryRetryLogs())


def _origin_of(exc: BaseException) -> str | None:
    """Lokasi kode (file:baris, fungsi) tempat error muncul — aman karena
    hanya nama file/baris/fungsi, tanpa isi variabel maupun isi pesan."""
    frames = traceback.extract_tb(exc.__traceback__)
    # Utamakan frame milik kode kita, bukan frame di dalam library.
    own_frames = [frame for frame in frames if "site-packages" not in frame.filename]
    frame = (own_frames or frames or [None])[-1]
    if frame is None:
        return None
    return f"{os.path.basename(frame.filename)}:{frame.lineno} ({frame.name})"


def safe_error_summary(exc: BaseException) -> str:
    """Ringkasan error yang AMAN untuk ditulis ke log server.

    Pesan/traceback bawaan library sering memuat isi request atau isi baris
    data (mis. Postgres "Failing row contains (...)", pesan validasi Pydantic
    dengan input_value) — dan teks laporan warga bebas berisi data pribadi.
    Jadi yang dicatat hanya: tipe error, lokasi kode, dan pesan HANYA untuk
    tipe yang isinya diketahui tidak membawa data:
    - httpx.HTTPStatusError: kode status saja (pesan bawaannya memuat URL
      lengkap termasuk query string/token, jadi TIDAK boleh dicetak)
    - error koneksi httpx: pesan singkat ("Server disconnected", dst)
    - error PostgREST berkode PGRST*: kode + pesan (soal skema/JWT, bukan data)
    - error database lain: kode saja (pesan/`details` bisa memuat nilai data)
    - error API Google: kode HTTP saja
    - tipe lain: nama tipe saja
    """
    name = type(exc).__name__

    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"http={exc.response.status_code}"
    elif isinstance(exc, httpx.TransportError):
        detail = str(exc)
    elif isinstance(exc, PostgrestAPIError):
        code = str(exc.code or "")
        detail = f"code={code} message={exc.message}" if code.startswith("PGRST") else f"code={code}"
    elif isinstance(exc, GoogleAPICallError):
        detail = f"http={exc.code}"
    else:
        detail = ""

    summary = f"{name}: {detail}" if detail else name
    origin = _origin_of(exc)
    return f"{summary} di {origin}" if origin else summary
