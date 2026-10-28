import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from supabase import Client

from app.agents.risk_agent import WIB, to_wib
from app.agents.route_agent import (
    AlternativeRoute,
    FlaggedArea,
    PlaceQuery,
    RouteAgentDeps,
    RouteAssessment,
    RouteCheckResult,
    RoutePointError,
    describe_data_coverage,
    run_route_check,
)
from app.agents.route_analysis import RouteAnalysis, Segment
from app.core.config import get_settings
from app.core.directions import RouteNotFound, RouteServiceUnavailable
from app.core.rate_limit import enforce_route_check_rate_limit
from app.core.safe_log import safe_error_summary
from app.core.supabase_client import get_supabase
from app.schemas.route import (
    AlternativeRouteOut,
    FlaggedAreaOut,
    GeoLineStringOut,
    PlaceInput,
    PointOut,
    RouteCheckOut,
    RouteCheckRequest,
    RouteSummaryOut,
    SegmentOut,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/route", tags=["route"])


def get_route_agent_deps(supabase: Client = Depends(get_supabase)) -> RouteAgentDeps:
    """Ketergantungan Safe Route Advisor (Supabase + Mapbox + Gemini); di-override di test."""
    return RouteAgentDeps(supabase=supabase)


def _to_query(place: PlaceInput) -> PlaceQuery:
    return PlaceQuery(text=place.text, latitude=place.latitude, longitude=place.longitude)


def _line(points) -> GeoLineStringOut:
    """GeoJSON LineString dari titik (lintang, bujur). Keluaran memakai urutan [bujur, lintang], 5 desimal (~1 m)."""
    return GeoLineStringOut(coordinates=[[round(lon, 5), round(lat, 5)] for lat, lon in points])


def _area_out(area: FlaggedArea) -> FlaggedAreaOut:
    return FlaggedAreaOut(
        area_name=area.area_name,
        place_name=area.place_name,
        label=f"{area.area_name} ({area.place_name})" if area.place_name else area.area_name,
        latitude=round(area.latitude, 5),
        longitude=round(area.longitude, 5),
        time_bucket=area.time_bucket,
        risk_score=area.risk_score,
        risk_level=area.risk_level,
        segment_index=area.segment_index,
    )


def _segment_out(segment: Segment) -> SegmentOut:
    return SegmentOut(
        index=segment.index,
        road_name=segment.road_name,
        place_name=segment.place_name,
        start_km=round(segment.start_m / 1000, 3),
        end_km=round(segment.end_m / 1000, 3),
        length_m=round(segment.length_m),
        risk_level=segment.level,
        risk_score=segment.max_score,
        incident_count=segment.incident_count,
        dominant_category=segment.dominant_category,
        incident_hours=dict(sorted(segment.incident_hours.items())),
        has_nearby_data=segment.has_nearby_data,
        peak_time_bucket=segment.peak_bucket,
        geometry=_line(segment.geometry),
    )


def _summary(
    assessment: RouteAssessment, distance_km: float, duration_minutes: int, time_buckets: tuple[str, ...]
) -> RouteSummaryOut:
    coverage = describe_data_coverage(assessment, get_settings())
    return RouteSummaryOut(
        status=assessment.level,
        max_risk_score=assessment.max_risk_score,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        data_coverage=coverage.coverage,
        data_limited=coverage.limited,
        high_exposure_m=round(assessment.high_exposure_m),
        medium_exposure_m=round(assessment.medium_exposure_m),
        incident_count=assessment.incident_count,
        time_buckets=list(time_buckets),
    )


def _detail(analysis: RouteAnalysis | None) -> tuple[GeoLineStringOut, list[SegmentOut], list[str]]:
    if analysis is None:
        return GeoLineStringOut(coordinates=[]), [], []
    return _line(analysis.geometry), [_segment_out(s) for s in analysis.segments], list(analysis.reasons)


def _alternative_out(alternative: AlternativeRoute) -> AlternativeRouteOut:
    coverage = describe_data_coverage(alternative.assessment, get_settings())
    time_buckets = alternative.analysis.time_buckets if alternative.analysis else ()
    geometry, segments, reasons = _detail(alternative.analysis)
    return AlternativeRouteOut(
        risk_level=alternative.assessment.level,
        max_risk_score=alternative.assessment.max_risk_score,
        distance_km=alternative.distance_km,
        duration_minutes=alternative.duration_minutes,
        data_coverage=coverage.coverage,
        data_limited=coverage.limited,
        is_lowest_risk=alternative.is_lowest_risk,
        extra_minutes=alternative.extra_minutes,
        summary=_summary(alternative.assessment, alternative.distance_km, alternative.duration_minutes, time_buckets),
        geometry=geometry,
        segments=segments,
        reasons=reasons,
    )


def _to_response(result: RouteCheckResult) -> RouteCheckOut:
    assessment = result.assessment
    coverage = describe_data_coverage(assessment, get_settings())
    geometry, segments, reasons = _detail(result.analysis)
    best = next((i for i, a in enumerate(result.alternatives, start=1) if a.is_lowest_risk), 0)
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
        data_coverage=coverage.coverage,
        data_limited=coverage.limited,
        data_note=coverage.note,
        location_notes=list(result.location_notes),
        alternatives=[_alternative_out(a) for a in result.alternatives],
        safer_alternative_available=best != 0,
        summary=_summary(assessment, result.distance_km, result.duration_minutes, result.time_buckets),
        geometry=geometry,
        segments=segments,
        reasons=reasons,
        recommended_route=best,
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
    """Cek Rute Aman (REQ-F-030/031/032): menelusuri jalan yang dilalui rute asal -> tujuan, memeriksa
    riwayat kejadian di sekitar jalur pada jam perjalanan, dan menilai aman/waspada/berisiko_tinggi beserta
    alasannya — publik, tanpa login.

    Input divalidasi di sini oleh Pydantic (RouteCheckRequest) dan titik harus berada di wilayah Yogyakarta;
    waktu berangkat di masa lalu (> 5 menit) ditolak. Penilaian status bersifat deterministik
    (route_agent/route_analysis); `include_narrative` hanya menambah penjelasan Gemini yang opsional. Tidak ada
    data pengguna yang disimpan, dan respons hanya memuat agregat per ruas jalan (tanpa koordinat atau
    deskripsi insiden individual). Semua kegagalan dipetakan ke pesan Indonesia yang aman.
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
