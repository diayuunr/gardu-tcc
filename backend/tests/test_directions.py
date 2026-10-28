import logging

import httpx
import pytest

from app.core import geocoding
from app.core.config import get_settings
from app.core.directions import RouteNotFound, RouteServiceUnavailable, fetch_route
from app.core.geocoding import describe_area

TOKEN = "dummy-token-not-real"
ORIGIN = (-7.812995, 110.39872)
DESTINATION = (-7.783, 110.367)


@pytest.fixture(autouse=True)
def mapbox_configured(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", TOKEN)
    get_settings.cache_clear()
    geocoding._area_name_cache.clear()
    yield
    get_settings.cache_clear()
    geocoding._area_name_cache.clear()


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload, self.status_code = payload, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", f"https://api.mapbox.com/x?access_token={TOKEN}")
            raise httpx.HTTPStatusError(
                f"Server error for url {request.url}", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        return self._payload


def _stub_httpx_get(monkeypatch, response):
    """Ganti httpx.get: catat panggilan, kembalikan `response` (tanpa jaringan)."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params})
        return response

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


_OK_ROUTE = {
    "code": "Ok",
    "routes": [
        {
            "geometry": {"coordinates": [[110.39872, -7.812995], [110.38, -7.80], [110.367, -7.783]]},
            "distance": 4800.5,
            "duration": 1260.0,
        }
    ],
}


# ------------------------------------------------------------------ Directions


def test_fetch_route_parses_geometry_as_lat_lon_and_sends_lon_lat_to_mapbox(monkeypatch):
    calls = _stub_httpx_get(monkeypatch, _Response(_OK_ROUTE))

    route = fetch_route(ORIGIN, DESTINATION)

    assert route.points[0] == (-7.812995, 110.39872) and route.points[-1] == (-7.783, 110.367)  # (lat, lon)
    assert (route.distance_m, route.duration_s) == (4800.5, 1260.0)
    assert "110.39872,-7.812995;110.367,-7.783" in calls[0]["url"]  # Mapbox: bujur,lintang
    assert calls[0]["params"]["geometries"] == "geojson"


def test_no_route_and_service_failures_map_to_distinct_domain_errors(monkeypatch):
    _stub_httpx_get(monkeypatch, _Response({"code": "NoRoute", "routes": []}))
    with pytest.raises(RouteNotFound):
        fetch_route(ORIGIN, DESTINATION)

    for bad_payload in (
        {"code": "Ok", "routes": [{"geometry": {"coordinates": [[110.3, -7.8]]}, "distance": 1, "duration": 1}]},  # 1 titik
        {"code": "Ok", "routes": [{"geometry": {"coordinates": [[110.3, float("nan")], [110.4, -7.8]]}, "distance": 1, "duration": 1}]},
        {"code": "Ok", "routes": [{"distance": 1}]},  # tanpa geometri
        {"code": "InvalidInput"},
    ):
        _stub_httpx_get(monkeypatch, _Response(bad_payload))
        with pytest.raises(RouteServiceUnavailable):
            fetch_route(ORIGIN, DESTINATION)


def test_http_failure_never_leaks_the_mapbox_token_in_errors_or_logs(monkeypatch, caplog):
    _stub_httpx_get(monkeypatch, _Response({}, status_code=500))

    with caplog.at_level(logging.DEBUG), pytest.raises(RouteServiceUnavailable) as caught:
        fetch_route(ORIGIN, DESTINATION)

    assert TOKEN not in str(caught.value) and TOKEN not in caplog.text
    assert caught.value.__cause__ is None and caught.value.__suppress_context__  # tidak ada rantai ke error httpx
    assert all(record.exc_info is None for record in caplog.records)


def test_missing_token_fails_without_calling_mapbox(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "")
    get_settings.cache_clear()
    calls = _stub_httpx_get(monkeypatch, _Response(_OK_ROUTE))

    with pytest.raises(RouteServiceUnavailable):
        fetch_route(ORIGIN, DESTINATION)
    assert calls == []


# ------------------------------------------------------------ reverse geocoding


_KOTAGEDE = {"features": [{"text": "Kotagede", "context": [{"id": "region.1", "short_code": "ID-YO"}]}]}


def test_describe_area_returns_district_name_asks_only_for_locality_and_caches_success(monkeypatch):
    calls = _stub_httpx_get(monkeypatch, _Response(_KOTAGEDE))

    assert describe_area(-7.815, 110.395) == "Kotagede"
    assert describe_area(-7.815, 110.395) == "Kotagede"

    assert len(calls) == 1  # hasil sukses di-cache
    assert calls[0]["params"]["types"] == "locality"  # tingkat kecamatan/desa, bukan alamat


def test_describe_area_failures_are_not_cached_and_foreign_regions_are_ignored(monkeypatch, caplog):
    _stub_httpx_get(monkeypatch, _Response({}, status_code=429))
    with caplog.at_level(logging.DEBUG):
        assert describe_area(-7.815, 110.395) is None  # gagal -> None, tidak melempar
    assert TOKEN not in caplog.text

    _stub_httpx_get(monkeypatch, _Response(_KOTAGEDE))
    assert describe_area(-7.815, 110.395) == "Kotagede"  # kegagalan sebelumnya tidak "menempel"

    klaten = {"features": [{"text": "Klaten", "context": [{"id": "region.2", "short_code": "ID-JT"}]}]}
    _stub_httpx_get(monkeypatch, _Response(klaten))
    assert describe_area(-7.70, 110.60) is None  # bukan wilayah DIY
