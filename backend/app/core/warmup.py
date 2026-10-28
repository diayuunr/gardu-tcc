"""Pemanasan cache saat server menyala.

Uji nyata: permintaan /route/check pertama setelah server menyala ~3 dtk lebih lambat karena direktori wilayah
(521 baris tabel `areas`) dan koneksi Supabase baru dimuat saat itu. Dimuat sekali di latar belakang saat startup,
permintaan pertama pengguna tidak menanggung biayanya. Kegagalan (DB belum siap, env hilang) TIDAK menghentikan
server: cache terisi saat dipakai pertama kali, seperti sebelumnya.
"""

import logging
import threading
from collections.abc import Callable

from app.core.areas import AreaDirectory, get_directory_or_none
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase

logger = logging.getLogger(__name__)


def warm_caches(
    client_factory: Callable[[], object] = get_supabase,
    directory_loader: Callable[[object], AreaDirectory | None] = get_directory_or_none,
) -> bool:
    """Isi cache direktori wilayah. True bila berhasil; tidak pernah melempar exception."""
    try:
        directory = directory_loader(client_factory())
    except Exception as exc:  # noqa: BLE001 - pemanasan hanya optimasi, bukan syarat server hidup
        logger.warning("Pemanasan cache dilewati: %s", safe_error_summary(exc))
        return False
    if directory is None:
        logger.warning("Pemanasan cache: direktori wilayah belum tersedia, dimuat saat dibutuhkan.")
        return False
    return True


def start_warmup_thread() -> threading.Thread:
    """Jalankan `warm_caches` di thread latar (tidak menunda server menerima permintaan)."""
    thread = threading.Thread(target=warm_caches, name="gardu-warmup", daemon=True)
    thread.start()
    return thread
