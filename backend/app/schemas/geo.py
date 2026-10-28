from typing import Literal

from pydantic import BaseModel


class PlaceHitOut(BaseModel):
    """Satu hasil pencarian tempat di DIY. Koordinat = titik tempat tersebut (data peta publik).

    `source` = asal data (urutan prioritas): `landmark` (daftar kurasi lokal) > `photon` (OpenStreetMap) >
    `nominatim` (OpenStreetMap, hanya bila Photon gagal) > `wilayah` (nama kecamatan/kelurahan, titik pusatnya) >
    `mapbox` (cadangan). `category` = jenis tempat bila diketahui (kampus, transportasi, ..., atau tingkat wilayah)."""

    label: str
    place_name: str
    latitude: float
    longitude: float
    source: Literal["landmark", "photon", "nominatim", "wilayah", "mapbox"]
    category: str | None = None


class PlaceSearchOut(BaseModel):
    """`degraded` = ada lapisan pencarian yang sedang gagal sehingga hasil mungkin kurang lengkap (bukan error)."""

    count: int
    results: list[PlaceHitOut]
    degraded: bool = False


class ReverseOut(BaseModel):
    """Label wilayah untuk titik GPS: kecamatan terdekat + kabupaten/kota — BUKAN alamat presisi. Koordinat
    yang dikirim tidak digemakan kembali."""

    label: str
    kecamatan_kode: str | None
    in_diy: bool
