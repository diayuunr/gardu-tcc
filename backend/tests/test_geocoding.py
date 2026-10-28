import logging

import httpx
import pytest

from app.core import geocoding
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _mapbox_token(monkeypatch):
    """Pastikan tiap test punya MAPBOX_TOKEN sendiri, tidak bocor antar test."""
    monkeypatch.setenv("MAPBOX_TOKEN", "test-mapbox-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_geocode_location_returns_coordinates_inside_yogyakarta(monkeypatch):
    def fake_get(_url, params=None, timeout=None):
        return httpx.Response(
            200,
            json={"features": [{"center": [110.3695, -7.7956], "place_name": "Jl. Malioboro"}]},
            request=httpx.Request("GET", "https://api.mapbox.com/x"),
        )

    monkeypatch.setattr(geocoding.httpx, "get", fake_get)

    result = geocoding.geocode_location("Jl. Malioboro")

    assert result == (-7.7956, 110.3695)


def test_geocode_location_ignores_result_outside_yogyakarta(monkeypatch):
    def fake_get(_url, params=None, timeout=None):
        # Koordinat Jakarta, jauh di luar bbox Yogyakarta — harus diabaikan.
        return httpx.Response(
            200,
            json={"features": [{"center": [106.8456, -6.2088], "place_name": "Jakarta"}]},
            request=httpx.Request("GET", "https://api.mapbox.com/x"),
        )

    monkeypatch.setattr(geocoding.httpx, "get", fake_get)

    result = geocoding.geocode_location("Jl. Sudirman")

    assert result is None


def test_geocode_location_rejects_bordering_region_inside_bbox(monkeypatch):
    """Regresi untuk bug nyata: "Alun-Alun Kidul"/"Tugu Yogyakarta" pernah
    ke-geocode ke desa bernama sama di Klaten (Jawa Tengah, region ID-JT)
    karena Klaten berbatasan langsung dengan DIY dan tetap masuk bbox
    longgar. Koordinatnya secara lat/lon ada di dalam bbox, tapi context
    region-nya bukan ID-YO — harus ditolak.
    """

    def fake_get(_url, params=None, timeout=None):
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "center": [110.69762, -7.77396],  # masih di dalam bbox DIY
                        "place_name": "Tugu, Cawas, Klaten, Central Java, Indonesia",
                        "context": [
                            {"id": "locality.1", "text": "Cawas"},
                            {"id": "place.1", "text": "Klaten"},
                            {"id": "region.1", "short_code": "ID-JT", "text": "Central Java"},
                            {"id": "country.1", "short_code": "id", "text": "Indonesia"},
                        ],
                    }
                ]
            },
            request=httpx.Request("GET", "https://api.mapbox.com/x"),
        )

    monkeypatch.setattr(geocoding.httpx, "get", fake_get)

    result = geocoding.geocode_location("Tugu Yogyakarta")

    assert result is None


def test_failure_log_never_contains_mapbox_token_or_location_text(monkeypatch, caplog):
    secret_token = "pk.SECRET-TOKEN-MAPBOX"
    location = "Rumah Pak Budi Jl. Rahasia Nomor 5"

    def unauthorized_get(url, params=None, timeout=None):
        request = httpx.Request("GET", f"{url}?access_token={secret_token}")
        return httpx.Response(401, request=request)

    # Bukti tes ini tidak kosong: pesan mentah httpx memang memuat token.
    with pytest.raises(httpx.HTTPStatusError) as raw_error:
        unauthorized_get("https://api.mapbox.com/x.json").raise_for_status()
    assert secret_token in str(raw_error.value)

    monkeypatch.setattr(geocoding.httpx, "get", unauthorized_get)

    with caplog.at_level(logging.DEBUG, logger="app.core.geocoding"):
        result = geocoding.geocode_location(location)

    assert result is None
    assert "SECRET-TOKEN-MAPBOX" not in caplog.text
    assert "access_token" not in caplog.text
    assert "Rahasia" not in caplog.text and "Pak Budi" not in caplog.text
    assert any("http=401" in record.getMessage() for record in caplog.records)
    assert all(record.exc_info is None for record in caplog.records)


def test_info_logs_never_contain_location_text(monkeypatch, caplog):
    """Jalur 'tidak ada hasil', 'di luar bbox', dan 'region bukan DIY' dulu
    mencetak teks lokasi (bisa berisi alamat rumah) di log."""
    location = "Rumah Pak Budi Jl. Rahasia Nomor 5"
    scenarios = [
        {"features": []},
        {"features": [{"center": [106.8456, -6.2088], "place_name": "Jakarta"}]},
        {
            "features": [
                {
                    "center": [110.69762, -7.77396],
                    "place_name": "Tugu, Cawas, Klaten",
                    "context": [{"id": "region.1", "short_code": "ID-JT", "text": "Central Java"}],
                }
            ]
        },
    ]

    for body in scenarios:
        monkeypatch.setattr(
            geocoding.httpx,
            "get",
            lambda _url, params=None, timeout=None, body=body: httpx.Response(
                200, json=body, request=httpx.Request("GET", "https://api.mapbox.com/x")
            ),
        )
        with caplog.at_level(logging.DEBUG, logger="app.core.geocoding"):
            assert geocoding.geocode_location(location) is None

    assert "Rahasia" not in caplog.text and "Pak Budi" not in caplog.text
    # Hasil geocoding (koordinat & place_name) diturunkan dari teks yang diketik pengguna
    # (bisa alamat rumah), jadi juga tidak boleh masuk log.
    assert "6.2088" not in caplog.text and "106.8456" not in caplog.text
    assert "7.7739" not in caplog.text and "110.6976" not in caplog.text
    assert "Jakarta" not in caplog.text and "Cawas" not in caplog.text and "Klaten" not in caplog.text
    assert "ID-JT" in caplog.text  # kode region (bukan data pribadi) tetap dicatat untuk diagnosis
    assert len(caplog.records) == len(scenarios)  # tiap skenario tetap meninggalkan jejak log


def test_geocode_location_returns_none_without_token(monkeypatch):
    # setenv ke string kosong, BUKAN delenv — kalau cuma di-delenv, pydantic-settings
    # jatuh balik baca MAPBOX_TOKEN dari file backend/.env di disk (yang di mesin
    # developer bisa saja sudah diisi token asli), bikin test ini tidak hermetis.
    monkeypatch.setenv("MAPBOX_TOKEN", "")
    get_settings.cache_clear()

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Tidak boleh memanggil Mapbox kalau token belum diset")

    monkeypatch.setattr(geocoding.httpx, "get", fail_if_called)

    result = geocoding.geocode_location("Jl. Kaliurang")

    assert result is None
