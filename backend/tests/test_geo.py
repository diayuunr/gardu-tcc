"""Tes D1: GET /geo/search (pencarian berlapis) dan GET /geo/reverse (label wilayah dari data sendiri).

Logika lapisan (landmark/Photon/wilayah/Mapbox, dedupe, cache, sirkuit pemutus) diuji di test_place_search.py;
di sini lapisan HTTP-nya: bentuk respons, validasi, rate limit, dan privasi."""

import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from place_helpers import SAMPLE_LANDMARKS, TOKEN, install, mapbox_feature, photon_feature

from app.core import landmarks, places
from app.core.areas import Area, AreaDirectory, reset_area_directory_cache
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _env_and_clean_state(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", TOKEN)
    get_settings.cache_clear()
    places.clear_place_cache()
    reset_area_directory_cache()
    monkeypatch.setattr(landmarks, "get_landmarks", lambda: SAMPLE_LANDMARKS)
    app.dependency_overrides[get_supabase] = lambda: _EmptyDb()
    yield
    app.dependency_overrides.pop(get_supabase, None)
    get_settings.cache_clear()
    places.clear_place_cache()
    reset_area_directory_cache()


class _EmptyDb:
    """Tabel areas kosong: lapisan wilayah dan nama kecamatan tidak aktif (diuji terpisah)."""

    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def order(self, *_a):
        return self

    def range(self, *_a):
        return self

    def execute(self):
        from types import SimpleNamespace

        return SimpleNamespace(data=[])


# ============================================================================ search


def test_search_returns_landmarks_first_with_source_and_category_and_needs_no_network_for_them(monkeypatch):
    calls = install(monkeypatch, photon=[photon_feature("Universitas Gadjah Mada", 110.3804, -7.7694)])

    response = client.get("/geo/search", params={"q": "UGM", "limit": 1})

    body = response.json()
    assert response.status_code == 200 and body["degraded"] is False
    assert body["results"] == [{
        "label": "Universitas Gadjah Mada", "place_name": "Universitas Gadjah Mada", "latitude": -7.7716,
        "longitude": 110.3775, "source": "landmark", "category": "kampus",
    }]
    assert calls == []  # landmark memenuhi limit: tanpa jaringan sama sekali


def test_search_merges_layers_in_priority_order_and_reports_each_source(monkeypatch):
    install(monkeypatch, photon=[photon_feature("Warung Tugu Kopi", 110.3680, -7.7840, osm_value="cafe")])

    body = client.get("/geo/search", params={"q": "tugu", "limit": 5}).json()

    sources = [r["source"] for r in body["results"]]
    assert sources[0] == "landmark" and "photon" in sources
    assert sources == sorted(sources, key=["landmark", "photon", "wilayah", "mapbox"].index)  # urutan prioritas
    assert {r["label"] for r in body["results"]} >= {"Tugu Yogyakarta", "Warung Tugu Kopi"}


def test_search_validates_input_in_indonesian(monkeypatch):
    calls = install(monkeypatch)

    for params in ({"q": "ab"}, {"q": "  ab  "}, {"q": "x" * 101}, {"q": "tugu", "limit": 0}, {"q": "tugu", "limit": 11}, {}):
        response = client.get("/geo/search", params=params)
        assert response.status_code == 422, params
        assert isinstance(response.json()["detail"], str)
    assert "minimal 3 karakter" in client.get("/geo/search", params={"q": "ab"}).json()["detail"]
    assert calls == []  # input tak valid tidak pernah sampai ke layanan eksternal


def test_search_never_returns_5xx_when_every_network_layer_is_down(monkeypatch):
    install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"), mapbox_exc=httpx.ConnectTimeout("x"))

    response = client.get("/geo/search", params={"q": "kopi klotok"})

    assert response.status_code == 200
    assert response.json() == {"count": 0, "results": [], "degraded": True}
    assert response.headers["cache-control"] == "no-store"  # hasil sebagian jangan di-cache browser


def test_search_has_its_own_per_ip_rate_limit(monkeypatch):
    monkeypatch.setenv("GEO_SEARCH_RATE_LIMIT_MAX_REQUESTS", "2")
    get_settings.cache_clear()
    install(monkeypatch)

    statuses = [client.get("/geo/search", params={"q": f"tugu{i}"}).status_code for i in range(3)]

    assert statuses == [200, 200, 429]
    assert "pencarian tempat" in client.get("/geo/search", params={"q": "tugu9"}).json()["detail"]


def test_search_queries_and_tokens_are_never_logged_even_on_failures(monkeypatch, caplog):
    install(monkeypatch, photon_status=500, mapbox_status=500)

    with caplog.at_level(logging.DEBUG):
        client.get("/geo/search", params={"q": "rumah-pak-RAHASIA-KATA-KUNCI"})

    assert "RAHASIA" not in caplog.text and TOKEN not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_search_response_never_exposes_tokens_or_provider_urls(monkeypatch):
    install(monkeypatch, photon=[photon_feature("Kopi Klotok", 110.4, -7.69, osm_value="cafe")])

    text = client.get("/geo/search", params={"q": "klotok"}).text

    assert TOKEN not in text and "photon.komoot.io" not in text and "mapbox.com" not in text


# ============================================================================ reverse


def _directory():
    return AreaDirectory([
        Area("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557),
        Area("34.04.06", "Depok", "kecamatan", "34.04", -7.7700, 110.3900),
        Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
        Area("34.71.02", "Jetis", "kecamatan", "34.71", -7.7800, 110.3600),
        Area("34.02", "Kabupaten Bantul", "kabkota", None, -7.888, 110.3285),
        Area("34.02.09", "Jetis", "kecamatan", "34.02", -7.9100, 110.3200),
    ])


class _AreasDb:
    def __init__(self, areas, fail=False):
        self.areas, self.fail = areas, fail

    def table(self, _name):
        return self

    def select(self, *_a):
        return self

    def order(self, *_a):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("db down")
        rows = [
            {"kode": a.kode, "nama": a.nama, "tingkat": a.tingkat, "parent_kode": a.parent_kode, "latitude": a.latitude, "longitude": a.longitude}
            for a in self.areas._by_kode.values()
        ]
        from types import SimpleNamespace

        return SimpleNamespace(data=rows[self._range[0] : self._range[1] + 1])


def _reverse(lat, lon, db=None):
    app.dependency_overrides[get_supabase] = lambda: db or _AreasDb(_directory())
    try:
        return client.get("/geo/reverse", params={"lat": lat, "lon": lon})
    finally:
        app.dependency_overrides.pop(get_supabase, None)


def test_reverse_gives_the_kecamatan_label_from_our_own_data_without_mapbox(monkeypatch):
    calls = install(monkeypatch)

    response = _reverse(-7.7702, 110.3902)

    assert response.status_code == 200
    assert response.json() == {"label": "Kec. Depok, Kabupaten Sleman", "kecamatan_kode": "34.04.06", "in_diy": True}
    assert calls == []  # tidak memanggil Mapbox
    assert "-7.77" not in response.text and "110.39" not in response.text  # koordinat tidak digemakan


def test_reverse_does_not_repeat_the_parent_for_duplicate_kecamatan_names():
    body = _reverse(-7.7802, 110.3602).json()

    assert body["label"] == "Kec. Jetis (Kota Yogyakarta)"  # nama kembar sudah memuat induknya


def test_reverse_reports_points_outside_diy_as_in_diy_false_and_validates_ranges():
    outside = _reverse(-6.2, 106.8)  # Jakarta: jawaban 200 agar klien bisa menolak titik pin dengan pesan sendiri
    assert outside.status_code == 200
    assert outside.json() == {"label": "Di luar wilayah DIY", "kecamatan_kode": None, "in_diy": False}
    assert "-6.2" not in outside.text and "106.8" not in outside.text
    # Klaten dekat perbatasan tetapi di luar bbox DIY: tetap bukan DIY
    assert _reverse(-7.70, 110.90).json()["in_diy"] is False
    assert client.get("/geo/reverse", params={"lat": 95, "lon": 110}).status_code == 422
    assert client.get("/geo/reverse", params={"lat": -7.8}).status_code == 422


def test_reverse_falls_back_to_a_generic_label_when_far_from_any_kecamatan_or_data_is_down():
    far = _reverse(-8.20, 110.80)  # di DIY tetapi > 8 km dari kecamatan mana pun pada data uji
    assert far.json() == {"label": "Lokasi Anda (Yogyakarta)", "kecamatan_kode": None, "in_diy": True}

    reset_area_directory_cache()  # tanpa salinan cache, database mati -> label generik (bukan error)
    down = _reverse(-7.7702, 110.3902, db=_AreasDb(_directory(), fail=True))
    assert down.status_code == 200 and down.json()["label"] == "Lokasi Anda (Yogyakarta)"  # alur GPS tidak berhenti
