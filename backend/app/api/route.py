import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.agents.risk_agent import WIB, to_wib
from app.agents.route_agent import (
    FlaggedArea,
    PlaceQuery,
    RouteAgentDeps,
    RouteCheckResult,
    RoutePointError,
    run_route_check,
)
from app.core.directions import RouteNotFound, RouteServiceUnavailable
from app.core.rate_limit import enforce_route_check_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.route import (
    FlaggedAreaOut,
    PlaceInput,
    PointOut,
    RouteCheckOut,
    RouteCheckRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/route", tags=["route"])


def get_route_agent_deps(supabase: Client = Depends(get_supabase)) -> RouteAgentDeps:
    """Ketergantungan Safe Route Advisor (Supabase + Mapbox + Gemini); di-override di test."""
    return RouteAgentDeps(supabase=supabase)


def _to_query(place: PlaceInput) -> PlaceQuery:
    return PlaceQuery(text=place.text, latitude=place.latitude, longitude=place.longitude)


def _area_out(area: FlaggedArea) -> FlaggedAreaOut:
    return FlaggedAreaOut(
        area_name=area.area_name,
        place_name=area.place_name,
        latitude=area.latitude,
        longitude=area.longitude,
        time_bucket=area.time_bucket,
        risk_score=area.risk_score,
        risk_level=area.risk_level,
    )


def _to_response(result: RouteCheckResult) -> RouteCheckOut:
    assessment = result.assessment
    return RouteCheckOut(
        risk_level=assessment.level,
        max_risk_score=assessment.max_risk_score,
        areas_to_avoid=[_area_out(a) for a in assessment.flagged_areas if a.risk_level == "tinggi"],
        areas_to_watch=[_area_out(a) for a in assessment.flagged_areas if a.risk_level == "sedang"],
        areas_checked=assessment.areas_checked,
        areas_with_data=assessment.areas_with_data,
        origin=PointOut(latitude=result.origin[0], longitude=result.origin[1], place_name=result.origin_name),
        destination=PointOut(
            latitude=result.destination[0], longitude=result.destination[1], place_name=result.destination_name
        ),
        distance_km=result.distance_km,
        duration_minutes=result.duration_minutes,
        departure_time=result.departure_time,
        time_buckets=list(result.time_buckets),
        narrative=result.narrative,
    )


@router.post("/check", response_model=RouteCheckOut)
def check_route(
    payload: RouteCheckRequest,
    include_narrative: bool = Query(
        default=False,
        description=(
            "true = sertakan penjelasan Gemini (`narrative`) untuk rute waspada/berisiko tinggi. "
            "Default false: hasil deterministik saja, tanpa memanggil Gemini."
        ),
    ),
    deps: RouteAgentDeps = Depends(get_route_agent_deps),
    _rate_limit: None = Depends(enforce_route_check_rate_limit),
) -> RouteCheckOut:
    """Cek Rute Aman (REQ-F-030/031/032): apakah rute asal -> tujuan pada waktu berangkat
    tertentu melintasi area berskor kerawanan sedang/tinggi — publik, tanpa login.

    Input divalidasi di sini oleh Pydantic (RouteCheckRequest) dan titik harus berada
    di wilayah Yogyakarta. Penilaian status bersifat deterministik (route_agent);
    `include_narrative` hanya menambah penjelasan Gemini yang opsional. Tidak ada
    data pengguna yang disimpan. Semua kegagalan dipetakan ke pesan Indonesia yang
    aman (tanpa detail Mapbox/Supabase).
    """
    departure = to_wib(payload.departure_time) if payload.departure_time else datetime.now(WIB)
    try:
        result = run_route_check(
            deps, _to_query(payload.origin), _to_query(payload.destination), departure, include_narrative
        )
    except RoutePointError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from None
    except RouteNotFound:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rute antara kedua titik tidak ditemukan. Coba titik yang lebih dekat ke jalan.",
        ) from None
    except RouteServiceUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan peta/rute sedang tidak tersedia, silakan coba lagi.",
        ) from None
    except Exception as exc:  # noqa: BLE001 - error database/tak terduga wajib ditangani eksplisit, bukan silent fail
        # Tanpa exc_info/pesan mentah (lihat app/core/safe_log.py).
        logger.error("Pemeriksaan rute gagal: %s", safe_error_summary(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Pemeriksaan rute gagal diproses, silakan coba lagi.",
        ) from None

    return _to_response(result)
