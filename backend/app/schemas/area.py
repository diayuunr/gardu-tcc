from typing import Literal

from pydantic import BaseModel


class AreaOut(BaseModel):
    """Satu wilayah. Data publik statis: kode, nama, tingkat, induk, dan titik pusat wilayah
    (bukan alamat siapa pun). Koordinat null bila belum tersedia."""

    kode: str
    nama: str
    tingkat: Literal["kabkota", "kecamatan", "kelurahan"]
    parent_kode: str | None
    latitude: float | None
    longitude: float | None


class AreaListOut(BaseModel):
    count: int
    areas: list[AreaOut]
