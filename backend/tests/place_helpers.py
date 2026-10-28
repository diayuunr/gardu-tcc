"""Pembantu test pencarian tempat: Photon/Mapbox palsu yang dirutekan lewat URL, dan landmark sintetis."""

import httpx

from app.core.landmarks import Landmark

TOKEN = "dummy-token-not-real"

UGM = Landmark("Universitas Gadjah Mada", ("UGM", "Kampus UGM", "Bulaksumur"), "kampus", -7.7716, 110.3775, "tinggi")
YIA = Landmark("Bandara Internasional Yogyakarta", ("YIA", "Bandara YIA"), "transportasi", -7.9007, 110.0573, "tinggi")
TUGU = Landmark("Tugu Yogyakarta", ("Tugu Jogja", "Tugu"), "monumen", -7.78292, 110.36702, "tinggi")
STASIUN = Landmark("Stasiun Yogyakarta", ("Stasiun Tugu",), "transportasi", -7.78942, 110.36334, "tinggi")
MALIOBORO = Landmark("Malioboro", ("Jalan Malioboro",), "kawasan", -7.79278, 110.36580, "tinggi")
MALIOBORO_MALL = Landmark("Malioboro Mall", (), "belanja", -7.7932, 110.3653, "tinggi")
SAMPLE_LANDMARKS = (UGM, YIA, TUGU, STASIUN, MALIOBORO, MALIOBORO_MALL)


class Response:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload, self.status_code, self._bad_json = payload, status_code, bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", f"https://x.test/?q=RAHASIA-KATA-KUNCI&access_token={TOKEN}")
            raise httpx.HTTPStatusError(
                f"Server error for url {request.url}", request=request, response=httpx.Response(self.status_code, request=request)
            )

    def json(self):
        if self._bad_json:
            raise ValueError("bukan JSON")
        return self._payload


def photon_feature(name, lon, lat, *, state="Yogyakarta", city="Depok", county="Sleman", district=None, osm_value="university"):
    props = {"name": name, "state": state, "city": city, "county": county, "countrycode": "ID", "osm_value": osm_value}
    if district:
        props["district"] = district
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}


def mapbox_feature(text, lon, lat, region="ID-YO", full=None):
    return {
        "text": text,
        "place_name": full or f"{text}, Yogyakarta, Daerah Istimewa Yogyakarta, Indonesia",
        "center": [lon, lat],
        "context": [{"id": "region.123", "short_code": region}],
    }


def nominatim_item(name, lon, lat, *, state="Daerah Istimewa Yogyakarta", county="Kabupaten Sleman", village="Caturtunggal",
                   type_="cafe"):
    """Satu hasil format=jsonv2 Nominatim (lat/lon berupa teks, seperti aslinya)."""
    address = {"county": county, "state": state, "country_code": "id"}
    if village:
        address["village"] = village
    return {"name": name, "lat": str(lat), "lon": str(lon), "type": type_, "category": "amenity", "address": address,
            "display_name": f"{name}, {county}, {state}"}


def install(monkeypatch, *, photon=None, mapbox=None, photon_exc=None, mapbox_exc=None, photon_status=200, mapbox_status=200,
            photon_bad_json=False, nominatim=None, nominatim_exc=None, nominatim_status=200, nominatim_bad_json=False):
    """Ganti httpx.get: Photon ('photon' di URL), Nominatim ('nominatim') dan Mapbox dirutekan terpisah.
    Mengembalikan daftar panggilan {service, url, params, headers, timeout}."""
    calls: list[dict] = []

    def fake_get(url, params=None, headers=None, timeout=None, **_kwargs):
        service = "photon" if "photon" in url else "nominatim" if "nominatim" in url else "mapbox"
        calls.append({"service": service, "url": url, "params": params, "headers": headers, "timeout": timeout})
        exc = {"photon": photon_exc, "nominatim": nominatim_exc, "mapbox": mapbox_exc}[service]
        if exc is not None:
            raise exc
        if service == "photon":
            return Response({"features": photon or []}, photon_status, photon_bad_json)
        if service == "nominatim":
            return Response(nominatim or [], nominatim_status, nominatim_bad_json)
        return Response({"features": mapbox or []}, mapbox_status)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls
