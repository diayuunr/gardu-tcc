"""Tes end-to-end POST /route/check dengan skenario uji sintetis (tests/route_sample.py): bentuk respons untuk
frontend, urutan koordinat GeoJSON, alasan netral, alternatif, dan privasi (D6/D10)."""

import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from route_sample import DESTINATION, ORIGIN, SAMPLE_INCIDENTS, sample_deps

from app.agents.risk_agent import WIB
from app.api.route import get_route_agent_deps
from app.main import app

client = TestClient(app)
_VOCABULARY = {"klitih", "penyerangan", "bentrok antar kelompok", "begal/penodongan", "kejadian mencurigakan", "pengrusakan", "lainnya"}


def _all_numbers(value) -> set[float]:
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        return {round(float(value), 5)}
    if isinstance(value, dict):
        return set().union(*(_all_numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_all_numbers(v) for v in value)) if value else set()
    return set()


@pytest.fixture
def body():
    app.dependency_overrides[get_route_agent_deps] = sample_deps
    # Besok pukul 22.00 WIB: jam tetap "malam" (deterministik) dan tidak di masa lalu.
    departure = (datetime.now(WIB) + timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0, tzinfo=None)
    try:
        response = client.post(
            "/route/check",
            json={
                "origin": {"latitude": ORIGIN.latitude, "longitude": ORIGIN.longitude},
                "destination": {"latitude": DESTINATION.latitude, "longitude": DESTINATION.longitude},
                "departure_time": departure.isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(get_route_agent_deps, None)
    assert response.status_code == 200, response.text
    return response.json(), response.text


def test_top_level_shape_keeps_old_fields_and_adds_the_new_ones(body):
    data, _ = body

    assert set(data) >= {  # field lama yang dipakai frontend
        "risk_level", "max_risk_score", "areas_to_avoid", "areas_to_watch", "areas_checked", "areas_with_data",
        "origin", "destination", "distance_km", "duration_minutes", "departure_time", "time_buckets",
        "data_coverage", "data_limited", "data_note", "location_notes", "alternatives",
        "safer_alternative_available", "narrative",
    }
    assert set(data) >= {"summary", "geometry", "segments", "reasons", "recommended_route"}  # field baru
    assert data["risk_level"] == "berisiko_tinggi" and data["summary"]["status"] == data["risk_level"]
    assert data["summary"]["max_risk_score"] == data["max_risk_score"] and data["time_buckets"] == ["malam"]


def test_geometry_is_a_geojson_linestring_in_longitude_latitude_order(body):
    data, _ = body

    geometry = data["geometry"]
    assert geometry["type"] == "LineString" and len(geometry["coordinates"]) >= 2
    first = geometry["coordinates"][0]
    assert 110.3 < first[0] < 110.5 and -7.9 < first[1] < -7.6  # [bujur, lintang]: DIY ada di lon 110.x, lat -7.x
    assert len(geometry["coordinates"]) < 40  # sudah dijarangkan (rute asli ratusan titik)
    assert all(len(c) == 2 and re.fullmatch(r"-?\d+(\.\d{1,5})?", str(c[0])) for c in geometry["coordinates"])  # <= 5 desimal


def test_segments_are_ordered_contiguous_named_and_drawable(body):
    data, _ = body

    segments = data["segments"]
    assert [s["road_name"] for s in segments] == ["Jalan Cik Di Tiro", "Jalan Kaliurang", "Ring Road Utara", "jalan tanpa nama"]
    assert [s["index"] for s in segments] == [0, 1, 2, 3]
    for before, after in zip(segments, segments[1:]):
        assert before["end_km"] == pytest.approx(after["start_km"], abs=0.002)  # rentang bersambung
    assert segments[-1]["end_km"] == pytest.approx(data["distance_km"], abs=0.15)
    kaliurang = segments[1]
    assert kaliurang["risk_level"] == "tinggi" and kaliurang["place_name"] == "Kec. Depok"
    assert kaliurang["incident_count"] == 9 and kaliurang["dominant_category"] == "klitih"
    assert kaliurang["incident_hours"] == {"dini_hari": 2, "malam": 7} and kaliurang["peak_time_bucket"] == "malam"
    assert segments[0]["risk_level"] == "rendah" and segments[0]["incident_count"] == 0 and segments[0]["incident_hours"] == {}
    for segment in segments:
        assert segment["geometry"]["type"] == "LineString" and len(segment["geometry"]["coordinates"]) >= 2
        assert set(segment) == {
            "index", "road_name", "place_name", "start_km", "end_km", "length_m", "risk_level", "risk_score",
            "incident_count", "dominant_category", "incident_hours", "has_nearby_data", "peak_time_bucket", "geometry",
        }


def test_legacy_area_lists_are_now_road_segments_with_labels(body):
    data, _ = body

    [avoid] = data["areas_to_avoid"]
    assert (avoid["area_name"], avoid["place_name"], avoid["label"]) == ("Jalan Kaliurang", "Kec. Depok", "Jalan Kaliurang (Kec. Depok)")
    assert avoid["risk_level"] == "tinggi" and avoid["segment_index"] == 1
    assert [a["label"] for a in data["areas_to_watch"]] == ["Ring Road Utara (Kec. Ngaglik)"]


def test_reasons_are_neutral_indonesian_and_do_not_promise_safety(body):
    data, text = body

    joined = " ".join(data["reasons"])
    assert "Melewati Jalan Kaliurang (Kec. Depok): 9 kejadian tercatat dalam radius 300 m dari jalur" in joined
    assert "Anda diperkirakan melintas pada jam malam" in joined
    for word in ("bahaya", "mengerikan", "dijamin", "pasti aman", "korban", "pelaku"):
        assert word not in text.lower()
    assert not re.search(r"-7\.\d{3,}", joined)  # alasan tanpa koordinat


def test_alternative_comes_with_its_own_map_data_reasons_and_is_recommended(body):
    data, _ = body

    assert data["safer_alternative_available"] is True and data["recommended_route"] == 1
    [alt] = data["alternatives"]
    assert alt["is_lowest_risk"] is True and alt["risk_level"] == "aman"
    assert alt["extra_minutes"] == alt["duration_minutes"] - data["duration_minutes"]  # konsisten dengan menit yang tampil
    assert alt["summary"]["status"] == "aman" and alt["geometry"]["type"] == "LineString"
    assert [s["road_name"] for s in alt["segments"]][0] == "Jalan Mangkubumi"
    assert any("Lebih rendah risikonya dibanding rute utama" in r for r in alt["reasons"])
    assert alt["data_coverage"] >= 0.8 * data["data_coverage"]  # datanya sebanding, bukan sekadar kurang data


def test_response_never_contains_individual_incident_coordinates_or_text(body):
    data, text = body

    numbers = _all_numbers(data)
    for incident in SAMPLE_INCIDENTS:  # tidak ada angka koordinat insiden mana pun di seluruh respons
        assert round(incident.latitude, 5) not in numbers and round(incident.longitude, 5) not in numbers
    for forbidden in ("description", "location_text", "incident_time", "incidents\"", "occurred_at"):
        assert forbidden not in text
    categories = {s["dominant_category"] for s in data["segments"] if s["dominant_category"]}
    assert categories <= _VOCABULARY  # hanya kategori umum dari kosakata tetap, bukan teks bebas
    assert all(set(s["incident_hours"]) <= {"dini_hari", "pagi", "siang", "sore", "malam"} for s in data["segments"])


def test_area_coordinates_are_segment_midpoints_not_score_peaks(body):
    data, _ = body

    segment = data["segments"][1]
    line = segment["geometry"]["coordinates"]
    [avoid] = data["areas_to_avoid"]
    lons, lats = [c[0] for c in line], [c[1] for c in line]
    assert min(lats) <= avoid["latitude"] <= max(lats) and min(lons) <= avoid["longitude"] <= max(lons)  # di jalur ruas itu
    # Titik tengah ruas: bukan di dekat kluster kejadian (Kaliurang utara, ~-7.7500), melainkan di tengah ruas panjang.
    assert abs(avoid["latitude"] - (-7.7500)) > 0.003


def test_payload_stays_small_enough_for_the_frontend(body):
    _, text = body

    assert len(text.encode()) < 60_000 and json.loads(text)
