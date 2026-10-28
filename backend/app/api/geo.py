import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.core.areas import AreasUnavailable, get_area_directory, get_directory_or_none, in_diy, kecamatan_label
from app.core.config import get_settings
from app.core import places
from app.core.rate_limit import enforce_geo_rate_limit
from app.core.supabase_client import get_supabase
from app.schemas.geo import PlaceHitOut, PlaceSearchOut, ReverseOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/geo", tags=["geo"])

_MIN_QUERY_LENGTH = 3


@router.get("/search", response_model=PlaceSearchOut, summary="Cari tempat (autocomplete)")
def search(
    response: Response,
    q: str = Query(..., max_length=100, description="Kata kunci (minimal 3 karakter setelah dirapikan)."),
    limit: int = Query(default=5, ge=1, le=10, description="Jumlah hasil maksimum."),
    supabase: Client = Depends(get_supabase),
    _rate_limit: None = Depends(enforce_geo_rate_limit),
) -> PlaceSearchOut:
    """Pencarian tempat untuk memilih asal/tujuan rute, dibatasi wilayah DIY, dari beberapa lapisan berurutan prioritas:
    `landmark` (daftar kurasi lokal: UGM, YIA, Malioboro, ...) > `photon` (OpenStreetMap) > `wilayah` (kecamatan/kelurahan
    dari tabel areas) > `mapbox` (cadangan terakhir). Duplikat (< 150 m dan nama mirip) dibuang; tiap hasil memuat
    `source`. Kegagalan satu lapisan TIDAK menjadi error: lapisan berikutnya dipakai dan `degraded` bernilai true.

    Tambahkan jeda (debounce ~300 ms) di sisi klien; ada batas per-IP dan cache LRU. Kata kunci tidak disimpan maupun
    dicatat di log. Hasil berisi nama tempat dan titik petanya (data peta publik), bukan data pengguna.
    """
    query = " ".join(q.split())
    if len(query) < _MIN_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Kata kunci pencarian minimal 3 karakter."
        )
    result = places.search(query, limit, get_directory_or_none(supabase))
    response.headers["Cache-Control"] = "no-store" if result.degraded else "private, max-age=60"
    return PlaceSearchOut(
        count=len(result.hits),
        results=[
            PlaceHitOut(
                label=h.label, place_name=h.place_name, latitude=h.latitude, longitude=h.longitude,
                source=h.source, category=h.category,
            )
            for h in result.hits
        ],
        degraded=result.degraded,
    )


@router.get("/reverse", response_model=ReverseOut, summary="Label wilayah untuk titik GPS")
def reverse(
    lat: float = Query(..., ge=-90, le=90, description="Lintang titik GPS."),
    lon: float = Query(..., ge=-180, le=180, description="Bujur titik GPS."),
    supabase: Client = Depends(get_supabase),
    _rate_limit: None = Depends(enforce_geo_rate_limit),
) -> ReverseOut:
    """Label wilayah (kecamatan terdekat + kabupaten/kota) untuk titik GPS atau titik yang dipilih pengguna di peta
    (pin drop), mis. "Kec. Depok, Kabupaten Sleman" — BUKAN alamat presisi. Dihitung dari data wilayah sendiri
    (tanpa Mapbox, tanpa menyimpan atau menggemakan koordinat). Titik di luar DIY dijawab `in_diy: false` (200)
    supaya klien bisa menampilkan pesan dan menolak titik itu. Bila data wilayah tidak terbaca, tetap dijawab
    dengan label generik supaya alur GPS tidak terhenti.
    """
    if not in_diy(lat, lon):
        return ReverseOut(label="Di luar wilayah DIY", kecamatan_kode=None, in_diy=False)
    try:
        directory = get_area_directory(supabase)
    except AreasUnavailable:
        return ReverseOut(label="Lokasi Anda (Yogyakarta)", kecamatan_kode=None, in_diy=True)

    kecamatan = directory.nearest_kecamatan(lat, lon, get_settings().risk_place_max_distance_meters)
    if kecamatan is None:
        return ReverseOut(label="Lokasi Anda (Yogyakarta)", kecamatan_kode=None, in_diy=True)
    return ReverseOut(label=kecamatan_label(directory, kecamatan), kecamatan_kode=kecamatan.kode, in_diy=True)
