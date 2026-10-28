import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from supabase import Client

from app.core.areas import KODE_REGEX, AreasUnavailable, get_area_directory
from app.core.supabase_client import get_supabase
from app.schemas.area import AreaListOut, AreaOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/areas", tags=["areas"])


@router.get("", response_model=AreaListOut, summary="Daftar wilayah berjenjang")
def list_areas(
    response: Response,
    tingkat: Literal["kabkota", "kecamatan", "kelurahan"] | None = Query(
        default=None, description="Filter tingkat wilayah."
    ),
    parent: str | None = Query(
        default=None, pattern=KODE_REGEX, description="Kode induk, mis. 34.04 untuk kecamatan di Sleman."
    ),
    supabase: Client = Depends(get_supabase),
) -> AreaListOut:
    """Wilayah DIY untuk dropdown berjenjang (kabkota > kecamatan > kelurahan), terurut nama.

    Publik tanpa login; hanya data wilayah (kode, nama, induk, titik pusat) — tidak ada data laporan.
    Sumbernya cache memori (`areas_cache_ttl_seconds`), jadi aman dipanggil tiap pengguna membuka
    form. Contoh: `GET /areas?tingkat=kabkota`, lalu `GET /areas?tingkat=kecamatan&parent=34.04`.
    """
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        directory = get_area_directory(supabase)
    except AreasUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Data wilayah sementara tidak dapat diambil, silakan coba lagi.",
        ) from None

    areas = directory.find(tingkat=tingkat, parent_kode=parent)
    return AreaListOut(
        count=len(areas),
        areas=[
            AreaOut(
                kode=area.kode,
                nama=area.nama,
                tingkat=area.tingkat,
                parent_kode=area.parent_kode,
                latitude=area.coordinates[0] if area.coordinates else None,
                longitude=area.coordinates[1] if area.coordinates else None,
            )
            for area in areas
        ],
    )
