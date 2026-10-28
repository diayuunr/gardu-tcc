"""Penyamaran (masking) data pribadi dalam teks bebas laporan (REQ-NF-120).

Warga kadang menulis nomor telepon, email, atau NIK dalam deskripsi. Teks itu TIDAK ditolak —
bagian pribadinya disamarkan sebelum disimpan dan sebelum dikirim ke embedding/Gemini:

- email                        -> "[email disamarkan]"
- NIK (16 digit)               -> "[nomor disamarkan]"
- nomor telepon (+62/62/08..., termasuk telepon rumah berkode area, dengan spasi/titik/strip
  sebagai pemisah)            -> "[nomor disamarkan]"

SENGAJA TIDAK disamarkan: nomor polisi kendaraan (mis. "AB 1234 CD") karena itu informasi kejadian
yang sah; juga jam ("02.30"), tanggal ("28-10-2026"), dan nominal uang ("Rp 50.000"). Pola telepon
hanya cocok untuk deretan angka berawalan 0 / 62 / +62 dengan kelompok angka >= 3 digit, sehingga
penulisan jam/tanggal/nominal yang berkelompok dua digit tidak ikut tersamar.

Batasan (heuristik, bukan jaminan): angka yang ditulis dengan huruf ("nol delapan satu dua ...")
atau disisipi kata tidak terdeteksi; pelapor tetap diingatkan di formulir agar tidak menulis
data pribadi. Fungsi ini idempoten: teks yang sudah disamarkan tidak berubah lagi.
"""

import re

EMAIL_MASK = "[email disamarkan]"
NUMBER_MASK = "[nomor disamarkan]"

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# NIK: 16 digit berurutan, atau 4 kelompok @4 digit dipisah spasi/strip.
_NIK = re.compile(r"(?<![\d\w])(?:\d{16}|\d{4}(?:[ -]\d{4}){3})(?![\d\w])")
# Telepon: (+62|62|0) + kode operator/area 2-4 digit + dua kelompok >= 3 digit (pemisah opsional).
_PHONE = re.compile(
    r"(?<![\w.])\(?(?:\+62|62|0)[ .-]?\(?\d{2,4}\)?[ .-]?\d{3,4}[ .-]?\d{3,5}(?![\w])"
)


def mask_personal_data(text: str) -> str:
    """Samarkan email, NIK, dan nomor telepon di `text`; bagian lain dibiarkan apa adanya."""
    masked = _EMAIL.sub(EMAIL_MASK, text)
    masked = _NIK.sub(NUMBER_MASK, masked)  # sebelum telepon: NIK berawalan 62... tidak boleh terpotong
    return _PHONE.sub(NUMBER_MASK, masked)
