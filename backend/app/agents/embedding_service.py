import logging

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from app.core.config import get_settings
from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

# text-embedding-004 di-retire Google per 14 Januari 2026 -> pakai
# gemini-embedding-001, dengan output_dimensionality dipaksa 768 supaya
# tetap konsisten dengan kolom `embedding vector(768)` yang sudah ada
# (model ini punya dimensi native 3072, WAJIB di-set eksplisit ke 768,
# tidak otomatis 768 begitu saja).
EMBEDDING_MODEL = "models/gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768


def generate_embedding(text: str) -> list[float] | None:
    """Ubah teks laporan jadi vector embedding lewat Gemini (REQ-F-014).

    Dipanggil dari Report Verification & Clustering Agent
    (app/agents/verify_agent.py) — bukan dipanggil langsung dari endpoint
    API mana pun, supaya pemanggilan API AI tetap terpusat di satu tempat.

    Tidak pernah melempar exception: kalau GEMINI_API_KEY belum diset atau
    panggilan API gagal, return None supaya laporan tetap tersimpan tanpa
    embedding (REQ-NF-110) dan bisa diproses ulang nanti.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        logger.info("GEMINI_API_KEY belum diset, lewati pembuatan embedding")
        return None

    try:
        embeddings_client = GoogleGenerativeAIEmbeddings(
            model=EMBEDDING_MODEL,
            google_api_key=settings.gemini_api_key,
        )
        vector = embeddings_client.embed_query(text, output_dimensionality=EMBEDDING_DIMENSIONS)
    except Exception as exc:  # noqa: BLE001 - semua error panggilan AI wajib ditangani eksplisit
        # Bukan `exc` mentah: request-nya memuat teks laporan (lihat app/core/safe_log.py).
        logger.warning("Gagal membuat embedding: %s", safe_error_summary(exc))
        return None

    if len(vector) != EMBEDDING_DIMENSIONS:
        logger.warning(
            "Dimensi embedding tidak sesuai (%d, diharapkan %d) — model mungkin berubah, embedding dibuang",
            len(vector),
            EMBEDDING_DIMENSIONS,
        )
        return None

    return vector
