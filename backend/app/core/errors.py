"""Penanganan error terpusat: semua respons error berbahasa Indonesia, berbentuk
`{"detail": "<pesan>"}`, dan tidak pernah memuat detail internal atau input pengguna.

- 422 validasi : `detail` berupa SATU kalimat ringkas (mudah ditampilkan frontend) + `errors`
                 per-field. Nilai yang dikirim pengguna (bisa teks laporan/koordinat) TIDAK
                 digemakan kembali dan tidak dicatat.
- 404/405/dst. : pesan bawaan Starlette (Inggris) diganti terjemahan; `detail` kustom dari
                 endpoint (sudah Indonesia) dipertahankan apa adanya.
- 500          : middleware menangkap exception tak terduga, mencatat hanya tipe error + lokasi
                 kode + method/path (tanpa query string, tanpa traceback, tanpa pesan mentah),
                 dan menjawab 500 generik. Middleware ini dipasang DI DALAM CORS supaya respons
                 error tetap membawa header CORS (kalau tidak, browser menampilkan "CORS error"
                 yang menyesatkan alih-alih pesan error).
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.safe_log import safe_error_summary

logger = logging.getLogger(__name__)

_MAX_REPORTED_ERRORS = 5
GENERIC_SERVER_ERROR = "Terjadi kesalahan pada server, silakan coba lagi."

_STATUS_MESSAGES = {
    400: "Permintaan tidak valid.",
    401: "Autentikasi diperlukan.",
    403: "Akses ditolak.",
    404: "Alamat yang diminta tidak ditemukan.",
    405: "Metode permintaan tidak diizinkan untuk alamat ini.",
    408: "Permintaan terlalu lama, silakan coba lagi.",
    413: "Isi permintaan terlalu besar.",
    422: "Input tidak valid.",
    429: "Terlalu banyak permintaan, coba lagi nanti.",
    500: GENERIC_SERVER_ERROR,
    502: "Layanan sementara tidak dapat diakses, silakan coba lagi.",
    503: "Layanan sedang tidak tersedia, silakan coba lagi.",
    504: "Layanan terlalu lama merespons, silakan coba lagi.",
}

_FIELD_LABELS = {
    "description": "Deskripsi",
    "location_text": "Lokasi",
    "latitude": "Lintang",
    "longitude": "Bujur",
    "lat": "Lintang",
    "lon": "Bujur",
    "occurred_at": "Waktu kejadian",
    "time_bucket": "Rentang waktu",
    "at": "Waktu",
    "origin": "Titik asal",
    "destination": "Titik tujuan",
    "departure_time": "Waktu berangkat",
    "text": "Teks lokasi",
    "include_narrative": "Parameter narasi",
    "kabkota_kode": "Kabupaten/kota",
    "kecamatan_kode": "Kecamatan",
    "kelurahan_kode": "Kelurahan",
    "jalan": "Nama jalan",
    "q": "Kata kunci",
    "limit": "Batas jumlah",
}


def _error_message(error: dict) -> str:
    """Pesan Indonesia untuk satu error validasi Pydantic (tanpa menggemakan nilai input)."""
    kind, ctx = error.get("type", ""), error.get("ctx") or {}
    if kind == "missing":
        return "wajib diisi"
    if kind == "string_too_short":
        return f"minimal {ctx.get('min_length')} karakter"
    if kind == "string_too_long":
        return f"maksimal {ctx.get('max_length')} karakter"
    if kind in ("greater_than_equal", "greater_than", "less_than_equal", "less_than"):
        symbol = {"greater_than_equal": "≥", "greater_than": ">", "less_than_equal": "≤", "less_than": "<"}[kind]
        limit = next((ctx[k] for k in ("ge", "gt", "le", "lt") if k in ctx), "")
        return f"harus {symbol} {limit}"
    if kind.startswith(("datetime", "date_", "time_")) or kind in ("date_type", "time_type"):
        return "format tanggal/waktu tidak valid (contoh: 2026-09-20T22:00:00)"
    if kind.startswith("bool"):
        return "harus bernilai true atau false"
    if kind.startswith(("float", "int", "finite")) or kind == "decimal_parsing":
        return "harus berupa angka"
    if kind in ("literal_error", "enum"):
        expected = ctx.get("expected")
        return f"nilai tidak valid, pilihan: {expected}" if expected else "nilai tidak valid"
    if kind == "value_error" and ctx.get("error") is not None:
        return str(ctx["error"])  # validator kustom kita, sudah berbahasa Indonesia
    if kind in ("json_invalid", "model_attributes_type", "dict_type", "model_type"):
        return "isi permintaan bukan JSON yang valid"
    if kind == "string_pattern_mismatch":
        return "format tidak valid"
    if kind == "extra_forbidden":
        return "field tidak dikenal"
    return "tidak valid"


def _field_path(loc: tuple) -> str:
    return ".".join(str(part) for part in loc if part not in ("body", "query", "path", "header"))


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": _field_path(tuple(err.get("loc", ()))), "message": _error_message(err)}
        for err in exc.errors()[:_MAX_REPORTED_ERRORS]
    ]
    summary = "; ".join(
        # Error tingkat-model (tanpa field) sudah berupa kalimat utuh: tanpa label di depannya.
        f"{_FIELD_LABELS.get(e['field'].split('.')[-1], e['field'])}: {e['message']}" if e["field"] else e["message"]
        for e in errors[:3]
    )
    return JSONResponse(status_code=422, content={"detail": f"Input tidak valid — {summary}.", "errors": errors})


async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    english_default = HTTPStatus(exc.status_code).phrase if exc.status_code in HTTPStatus._value2member_map_ else None
    if not isinstance(detail, str) or not detail or detail == english_default:
        detail = _STATUS_MESSAGES.get(exc.status_code, "Terjadi kesalahan, silakan coba lagi.")
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=exc.headers)


class SafeErrorMiddleware:
    """ASGI middleware: exception tak terduga -> 500 generik berbahasa Indonesia + log aman."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 - lapisan terakhir: tidak boleh ada 500 mentah/traceback ke klien
            # Hanya method + path (BUKAN query string: bisa memuat koordinat pengguna) dan ringkasan
            # aman; tanpa exc_info supaya pesan error pustaka (bisa memuat teks laporan) tidak tercatat.
            logger.error(
                "Kesalahan tak terduga pada %s %s: %s", scope.get("method"), scope.get("path"), safe_error_summary(exc)
            )
            if response_started:
                return  # respons sudah terkirim sebagian; tidak ada yang bisa diperbaiki
            await JSONResponse(status_code=500, content={"detail": GENERIC_SERVER_ERROR})(scope, receive, send)


def install_error_handling(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_middleware(SafeErrorMiddleware)
