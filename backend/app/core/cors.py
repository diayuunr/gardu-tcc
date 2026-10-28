from urllib.parse import urlparse


class CorsConfigError(ValueError):
    """CORS_ALLOW_ORIGINS tidak valid; dilempar saat start supaya salah konfigurasi ketahuan
    saat deploy, bukan saat demo (browser memblokir diam-diam)."""


def parse_cors_origins(raw: str) -> list[str]:
    """Daftar origin dari nilai env dipisah koma.

    - spasi di sekitar entri dibuang, entri kosong diabaikan (`"a, ,b,"` -> `["a", "b"]`)
    - garis miring di akhir dibuang (browser mengirim origin tanpa `/`)
    - "*" DITOLAK: API ini memakai `allow_credentials=True`, dan wildcard + credentials tidak
      valid di spesifikasi CORS (Starlette memantulkan origin apa pun, membuka semua situs)
    - tiap entri harus berbentuk `http(s)://host[:port]` tanpa path
    """
    origins: list[str] = []
    for entry in raw.split(","):
        origin = entry.strip().rstrip("/")
        if not origin:
            continue
        if "*" in origin:
            raise CorsConfigError(
                "CORS_ALLOW_ORIGINS tidak boleh memakai wildcard '*' (API memakai credentials). "
                "Tulis origin frontend yang persis, mis. https://gardu.example.app"
            )
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path or parsed.query:
            raise CorsConfigError(
                f"Entri CORS_ALLOW_ORIGINS tidak valid: '{origin}'. Gunakan bentuk http(s)://host[:port] tanpa path."
            )
        if origin not in origins:
            origins.append(origin)
    if not origins:
        raise CorsConfigError("CORS_ALLOW_ORIGINS kosong: isi minimal satu origin frontend.")
    return origins
