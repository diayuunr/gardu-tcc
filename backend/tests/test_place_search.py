"""Tes pencarian tempat berlapis: normalisasi/alias landmark, Photon, wilayah, Mapbox, dedupe, cache, fallback.

Termasuk kasus nyata yang ditemukan di uji coba: Mapbox 0 hasil untuk landmark, hasil pertama Mapbox salah
cocok ke desa di Klaten (ID-JT), dan Photon mati."""

import json
import logging
from pathlib import Path

import httpx
import pytest
from place_helpers import SAMPLE_LANDMARKS, TOKEN, install, mapbox_feature, nominatim_item, photon_feature

from app.core import landmarks, places
from app.core.areas import Area, AreaDirectory
from app.core.config import get_settings
from app.core.landmarks import (
    LANDMARKS_PATH,
    LandmarkDataError,
    load_landmarks,
    match_landmarks,
    normalize,
    validate_landmarks,
)
from app.core.places import resolve_place, search

DIRECTORY = AreaDirectory([
    Area("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557),
    Area("34.04.06", "Depok", "kecamatan", "34.04", -7.7700, 110.3900),
    Area("34.04.06.2001", "Caturtunggal", "kelurahan", "34.04.06", -7.7650, 110.3800),
    Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
    Area("34.71.02", "Jetis", "kecamatan", "34.71", -7.7800, 110.3600),
    Area("34.02", "Kabupaten Bantul", "kabkota", None, -7.888, 110.3285),
    Area("34.02.09", "Jetis", "kecamatan", "34.02", -7.9100, 110.3200),
])


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", TOKEN)
    get_settings.cache_clear()
    places.clear_place_cache()
    monkeypatch.setattr(landmarks, "get_landmarks", lambda: SAMPLE_LANDMARKS)
    yield
    get_settings.cache_clear()
    places.clear_place_cache()


# ================================================================ normalisasi & alias


def test_normalization_unifies_case_punctuation_accents_and_spelling_variants():
    assert normalize("Jl. Malioboro") == normalize("jalan  MALIOBORO") == "jalan malioboro"
    assert normalize("Tugu Jogja") == normalize("tugu yogya") == normalize("Tugu Yogyakarta") == "tugu yogyakarta"
    assert normalize("Kraton") == "keraton" and normalize("Alun-Alun Kidul") == "alun alun kidul"
    assert normalize("Café Ünï") == "cafe uni"
    assert normalize("  ") == "" and normalize("!!!") == ""


@pytest.mark.parametrize(
    ("query", "expected_first"),
    [
        ("UGM", "Universitas Gadjah Mada"),
        ("ugm", "Universitas Gadjah Mada"),
        ("Universitas Gadjah Mada", "Universitas Gadjah Mada"),
        ("univ gadjah", "Universitas Gadjah Mada"),  # autocomplete: setiap kata awalan dari kata nama
        ("kampus ugm", "Universitas Gadjah Mada"),
        ("bulaksumur", "Universitas Gadjah Mada"),
        ("YIA", "Bandara Internasional Yogyakarta"),
        ("bandara yia", "Bandara Internasional Yogyakarta"),
        ("Tugu Jogja", "Tugu Yogyakarta"),
        ("tugu", "Tugu Yogyakarta"),
        ("Stasiun Tugu", "Stasiun Yogyakarta"),
        ("jl malioboro", "Malioboro"),
        ("universitas gadjah madah", "Universitas Gadjah Mada"),  # salah ketik ringan
    ],
)
def test_aliases_prefixes_and_typos_find_the_right_landmark_first(query, expected_first):
    assert match_landmarks(query, 5, SAMPLE_LANDMARKS)[0].nama == expected_first


def test_exact_match_outranks_longer_names_and_unrelated_or_too_short_queries_match_nothing():
    assert [l.nama for l in match_landmarks("malioboro", 5, SAMPLE_LANDMARKS)] == ["Malioboro", "Malioboro Mall"]
    assert match_landmarks("warung makan padang", 5, SAMPLE_LANDMARKS) == []
    assert match_landmarks("a", 5, SAMPLE_LANDMARKS) == [] and match_landmarks("", 5, SAMPLE_LANDMARKS) == []


# ===================================================================== validitas data


def test_the_real_landmark_file_is_valid_in_diy_and_free_of_duplicates():
    landmarks_ = load_landmarks(LANDMARKS_PATH)

    assert 100 <= len(landmarks_) <= 160
    # Ejaan varian ("Tugu Jogja" = "Tugu Yogyakarta") boleh menyatu DALAM satu entri, tetapi tidak antar entri.
    names = [normalize(n) for l in landmarks_ for n in {normalize(x) for x in l.names}]
    assert len(names) == len(set(names))
    assert len({normalize(l.nama) for l in landmarks_}) == len(landmarks_)
    assert all(l.keyakinan in {"tinggi", "sedang", "perlu_tinjau"} for l in landmarks_)
    for required in ("Universitas Gadjah Mada", "Bandara Internasional Yogyakarta", "Tugu Yogyakarta", "Malioboro", "Stasiun Yogyakarta"):
        assert any(l.nama == required for l in landmarks_), required


def test_real_landmarks_resolve_the_queries_that_failed_on_mapbox():
    real = load_landmarks(LANDMARKS_PATH)
    expectations = {
        "Universitas Gadjah Mada": "Universitas Gadjah Mada", "UGM": "Universitas Gadjah Mada", "Malioboro": "Malioboro",
        "Bandara YIA": "Bandara Internasional Yogyakarta", "YIA": "Bandara Internasional Yogyakarta",
        "Tugu Yogyakarta": "Tugu Yogyakarta", "Tugu Jogja": "Tugu Yogyakarta", "Stasiun Tugu": "Stasiun Yogyakarta",
        "UNY": "Universitas Negeri Yogyakarta", "Keraton": "Keraton Yogyakarta", "Alkid": "Alun-Alun Kidul",
        # tambahan: sekolah, rumah sakit, mal, jalan/kawasan, kuliner, pantai
        "UAD": "Universitas Ahmad Dahlan", "SMA Teladan": "SMA Negeri 1 Yogyakarta", "Muhi": "SMA Muhammadiyah 1 Yogyakarta",
        "Gejayan": "Jalan Gejayan", "jl affandi": "Jalan Gejayan", "ringroad utara": "Ring Road Utara",
        "SCH Sleman": "Sleman City Hall", "Yu Djum": "Gudeg Yu Djum Wijilan", "Drini": "Pantai Drini",
        "Kridosono": "Stadion Kridosono", "Monjali": "Monumen Jogja Kembali",
    }
    for query, expected in expectations.items():
        assert match_landmarks(query, 3, real)[0].nama == expected, query


def _entry(**overrides):
    entry = {"nama": "Tempat A", "alias": ["TA"], "kategori": "wisata", "lat": -7.8, "lon": 110.36, "keyakinan": "tinggi"}
    entry.update(overrides)
    return entry


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        ([_entry(lat=-6.2, lon=106.8)], "di luar DIY"),
        ([_entry(), _entry(nama="Tempat B", alias=["ta"])], "bentrok"),  # alias ganda lintas entri
        ([_entry(), _entry(nama="tempat a", alias=[])], "bentrok"),  # nama ganda (beda huruf)
        ([_entry(kategori="restoran")], "kategori"),
        ([_entry(keyakinan="yakin")], "keyakinan"),
        ([_entry(lat="x")], "lat/lon"),
        ([_entry(nama="  ")], "'nama' kosong"),
        ([_entry(alias=["", "x"])], "alias"),
        ([], "tidak kosong"),
    ],
)
def test_landmark_validation_rejects_bad_data_with_a_clear_message(entries, message):
    with pytest.raises(LandmarkDataError, match=message):
        validate_landmarks({"tempat": entries})


def test_validation_reports_every_problem_not_only_the_first():
    with pytest.raises(LandmarkDataError) as error:
        validate_landmarks({"tempat": [_entry(lat=-6.2, lon=106.8), _entry(nama="B", alias=[], kategori="x")]})

    assert "di luar DIY" in str(error.value) and "kategori" in str(error.value)


def test_a_missing_or_broken_landmark_file_disables_the_layer_instead_of_crashing(monkeypatch, tmp_path):
    monkeypatch.undo()  # pakai get_landmarks asli
    landmarks.get_landmarks.cache_clear()
    broken = tmp_path / "landmarks.json"
    broken.write_text("{bukan json", encoding="utf-8")
    monkeypatch.setattr(landmarks, "LANDMARKS_PATH", broken)
    try:
        assert landmarks.get_landmarks() == ()
        landmarks.get_landmarks.cache_clear()
        monkeypatch.setattr(landmarks, "LANDMARKS_PATH", tmp_path / "tidak-ada.json")
        assert landmarks.get_landmarks() == ()
    finally:
        landmarks.get_landmarks.cache_clear()


# ===================================================================== lapisan jaringan


def test_landmark_hit_that_fills_the_limit_never_touches_the_network(monkeypatch):
    calls = install(monkeypatch)

    result = search("UGM", 1)

    assert [(h.source, h.label) for h in result.hits] == [("landmark", "Universitas Gadjah Mada")]
    assert calls == [] and result.degraded is False


def test_landmark_place_name_never_carries_a_guessed_kecamatan(monkeypatch):
    # Uji nyata: UGM (Depok, Sleman) berlabel "Kec. Gondokusuman" karena kecamatan dipilih dari titik tengah
    # terdekat. Landmark kini hanya memakai namanya sendiri, direktori wilayah pun tersedia.
    install(monkeypatch)
    directory = AreaDirectory([
        Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
        Area("34.71.03", "Gondokusuman", "kecamatan", "34.71", -7.7800, 110.3800),
    ])

    [hit] = search("UGM", 1, directory).hits

    assert hit.place_name == "Universitas Gadjah Mada" and "Gondokusuman" not in hit.place_name


def test_cases_reported_from_real_testing_are_all_resolved_via_landmarks_when_mapbox_fails_them(monkeypatch):
    # Mapbox nyata: 0 hasil untuk UGM/Malioboro/YIA; "Tugu Yogyakarta" salah cocok ke desa Klaten (ID-JT).
    wrong_first = [mapbox_feature("Tugu", 110.64, -7.70, region="ID-JT", full="Tugu, Klaten, Jawa Tengah")]
    calls = install(monkeypatch, photon=[], mapbox=wrong_first)

    for query, label in (("Universitas Gadjah Mada", "Universitas Gadjah Mada"), ("Malioboro", "Malioboro"),
                         ("Bandara YIA", "Bandara Internasional Yogyakarta"), ("Tugu Yogyakarta", "Tugu Yogyakarta"),
                         ("Stasiun Tugu", "Stasiun Yogyakarta")):
        first = search(query, 5).hits[0]
        assert (first.source, first.label) == ("landmark", label), query
    assert resolve_place("Tugu Yogyakarta") == (-7.78292, 110.36702)
    assert not [c for c in calls if c["service"] == "mapbox"]  # Mapbox bahkan tidak dipanggil


def test_photon_results_are_filtered_to_diy_labelled_and_sent_with_a_clear_user_agent(monkeypatch):
    features = [
        photon_feature("Kopi Klotok", 110.4160, -7.6850, city="Pakem", county="Sleman", osm_value="cafe"),
        photon_feature("Kopi Klotok", 110.64, -7.70, state="Central Java", city="Klaten", county="Klaten"),  # state lain
        photon_feature("Kopi Jakarta", 106.8, -6.2, state="Jakarta"),  # di luar bbox
        photon_feature("Warung Sleman", 110.38, -7.71, city="Sleman", county="Sleman", osm_value="restaurant"),
        {"properties": {"name": "rusak"}},  # fitur rusak dilewati
    ]
    calls = install(monkeypatch, photon=features)

    hits = search("kopi klotok", 5).hits

    assert [(h.source, h.label, h.place_name) for h in hits] == [
        ("photon", "Kopi Klotok", "Kopi Klotok, Pakem, Sleman"),
        ("photon", "Warung Sleman", "Warung Sleman, Sleman"),  # tanpa pengulangan 'Sleman'
    ]
    assert hits[0].category == "cafe"
    [call] = [c for c in calls if c["service"] == "photon"]
    assert call["params"]["q"] == "kopi klotok" and call["params"]["bbox"] == "110.0,-8.25,110.85,-7.5"
    assert call["params"]["lat"] == -7.7956 and call["params"]["lon"] == 110.3695  # bias ke Yogyakarta
    assert "Gardu" in call["headers"]["User-Agent"] and call["timeout"] == 3.0


def test_photon_failure_falls_through_to_the_next_layers_without_an_error(monkeypatch):
    calls = install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"), mapbox=[mapbox_feature("Kopi Klotok", 110.416, -7.685)])

    result = search("kopi klotok", 5, DIRECTORY)

    assert [h.source for h in result.hits] == ["mapbox"] and result.degraded is True
    assert [c["service"] for c in calls] == ["photon", "nominatim", "mapbox"]  # Photon gagal -> Nominatim ikut dicoba


@pytest.mark.parametrize("failure", [{"photon_status": 500}, {"photon_bad_json": True}, {"photon_exc": httpx.ReadTimeout("x")}])
def test_any_photon_failure_mode_is_survived_and_opens_the_circuit_breaker(monkeypatch, failure):
    calls = install(monkeypatch, **failure)

    first = search("kopi satu", 3)
    second = search("kopi dua", 3)  # dalam masa jeda: Photon tidak dipanggil lagi

    assert first.degraded is True
    assert len([c for c in calls if c["service"] == "photon"]) == 1
    assert second.hits == () or all(h.source != "photon" for h in second.hits)


def test_photon_is_tried_again_after_the_cooldown(monkeypatch):
    calls = install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"))
    search("kopi satu", 3)

    places._photon_down_until = 0.0  # masa jeda selesai
    later_calls = install(monkeypatch, photon=[photon_feature("Kopi Dua", 110.4, -7.7, osm_value="cafe")])
    result = search("kopi dua", 3)

    assert [h.label for h in result.hits] == ["Kopi Dua"]
    assert [c["service"] for c in later_calls] == ["photon"]
    assert [c["service"] for c in calls].count("photon") == 1


def test_photon_can_be_switched_off_by_configuration(monkeypatch):
    monkeypatch.setenv("GEO_PHOTON_ENABLED", "false")
    get_settings.cache_clear()
    calls = install(monkeypatch, photon=[photon_feature("Kopi", 110.4, -7.7)], mapbox=[mapbox_feature("Kopi X", 110.4, -7.7)])

    assert [h.source for h in search("kopi x", 3).hits] == ["mapbox"]
    assert not [c for c in calls if c["service"] == "photon"]


# ------------------------------------------------------------------------ wilayah


def test_area_names_are_searched_with_their_centre_coordinates_and_exact_matches_first(monkeypatch):
    install(monkeypatch)

    hits = search("depok", 5, DIRECTORY).hits

    assert [(h.source, h.label) for h in hits] == [("wilayah", "Kec. Depok")]
    assert hits[0].place_name == "Kec. Depok, Kabupaten Sleman" and (hits[0].latitude, hits[0].longitude) == (-7.77, 110.39)
    assert hits[0].category == "kecamatan"

    desa = search("caturtunggal", 5, DIRECTORY).hits[0]
    assert desa.label == "Desa Caturtunggal" and desa.place_name == "Desa Caturtunggal, Kec. Depok, Kabupaten Sleman"


def test_duplicate_kecamatan_names_stay_distinguishable(monkeypatch):
    install(monkeypatch)

    labels = sorted(h.label for h in search("jetis", 5, DIRECTORY).hits)

    assert labels == ["Kec. Jetis (Kabupaten Bantul)", "Kec. Jetis (Kota Yogyakarta)"]


def test_area_layer_is_skipped_without_a_directory_or_for_very_short_queries(monkeypatch):
    install(monkeypatch)

    assert search("depok", 5, None).hits == ()
    assert search("de", 5, DIRECTORY).hits == ()


# ------------------------------------------------------------------------- mapbox


def test_mapbox_is_the_last_resort_and_picks_the_first_VALID_candidate_not_the_first_result(monkeypatch):
    candidates = [
        mapbox_feature("Desa Tugu", 110.64, -7.70, region="ID-JT", full="Tugu, Klaten, Jawa Tengah"),  # hasil ke-1: bukan DIY
        mapbox_feature("Jakarta", 106.8, -6.2),  # di luar bbox
        mapbox_feature("Pasar Kranggan", 110.3660, -7.7790, full="Pasar Kranggan, Yogyakarta"),  # yang pertama valid
    ]
    calls = install(monkeypatch, photon=[], mapbox=candidates)

    result = search("pasar kranggan", 5)

    assert [(h.source, h.label) for h in result.hits] == [("mapbox", "Pasar Kranggan")]
    [call] = [c for c in calls if c["service"] == "mapbox"]
    assert call["params"]["limit"] == 5 and call["params"]["country"] == "id"  # meminta kandidat, bukan hanya 1


def test_mapbox_zero_results_means_an_empty_list_not_an_error(monkeypatch):
    install(monkeypatch, photon=[], mapbox=[])

    result = search("tempat yang tidak ada", 5)

    assert result.hits == () and result.degraded is False  # 0 hasil yang sah, bukan kegagalan


def test_mapbox_is_only_called_when_earlier_layers_are_short_of_the_threshold(monkeypatch):
    calls = install(monkeypatch, photon=[photon_feature("Kopi X", 110.4, -7.7, osm_value="cafe")], mapbox=[mapbox_feature("Kopi Y", 110.41, -7.71)])

    assert [h.source for h in search("kopi", 5).hits] == ["photon"]
    assert not [c for c in calls if c["service"] == "mapbox"]  # default: hanya saat kosong

    monkeypatch.setenv("GEO_MAPBOX_FALLBACK_MIN_RESULTS", "3")
    get_settings.cache_clear()
    places.clear_place_cache()
    assert [h.source for h in search("kopi", 5).hits] == ["photon", "mapbox"]


def test_missing_mapbox_token_just_skips_that_layer(monkeypatch):
    monkeypatch.setenv("MAPBOX_TOKEN", "")
    get_settings.cache_clear()
    calls = install(monkeypatch, photon=[])

    assert search("tempat apa saja", 5).hits == ()
    assert not [c for c in calls if c["service"] == "mapbox"]


# ------------------------------------------------------------- dedupe & prioritas


def test_duplicates_close_by_with_similar_names_are_dropped_and_the_higher_priority_layer_wins(monkeypatch):
    install(monkeypatch, photon=[
        photon_feature("Universitas Gadjah Mada", 110.3780, -7.7718),  # ~40 m dari landmark: duplikat
        photon_feature("Fakultas Hukum Universitas Gadjah Mada", 110.3779, -7.7720),  # ~60 m, nama mengandung: duplikat
        photon_feature("Universitas Gadjah Mada", 110.5000, -7.9000),  # nama sama tapi jauh (> 150 m): dipertahankan
        photon_feature("Warung Bu Tini", 110.3776, -7.7717, osm_value="restaurant"),  # dekat tapi nama beda: dipertahankan
    ])

    hits = search("universitas gadjah mada", 10).hits

    assert [(h.source, h.label) for h in hits] == [
        ("landmark", "Universitas Gadjah Mada"), ("photon", "Universitas Gadjah Mada"), ("photon", "Warung Bu Tini"),
    ]
    assert (hits[1].latitude, hits[1].longitude) == (-7.9, 110.5)


def test_results_are_ordered_landmark_then_photon_then_wilayah_then_mapbox(monkeypatch):
    monkeypatch.setenv("GEO_MAPBOX_FALLBACK_MIN_RESULTS", "10")
    get_settings.cache_clear()
    directory = AreaDirectory([*DIRECTORY.find(), Area("34.71.50", "Tugu Anyar", "kecamatan", "34.71", -7.78, 110.37)])
    install(
        monkeypatch,
        photon=[photon_feature("Tugu Kopi", 110.3700, -7.7900, osm_value="cafe")],
        mapbox=[mapbox_feature("Tugu Pahlawan", 110.3500, -7.8000)],
    )

    sources = [h.source for h in search("tugu", 10, directory).hits]

    order = ["landmark", "photon", "wilayah", "mapbox"]
    assert sources == sorted(sources, key=order.index)  # tidak pernah urutan terbalik
    assert set(sources) == set(order)  # keempat lapisan benar-benar ikut


# ------------------------------------------------------------------------ cache


def test_identical_searches_hit_the_cache_regardless_of_case_and_spacing(monkeypatch):
    calls = install(monkeypatch, photon=[photon_feature("Kopi Klotok", 110.416, -7.685, osm_value="cafe")])

    search("kopi klotok", 5)
    search("  Kopi   KLOTOK ", 5)

    assert len([c for c in calls if c["service"] == "photon"]) == 1


def test_cache_is_lru_least_recently_used_entries_are_evicted_first(monkeypatch):
    monkeypatch.setenv("GEO_SEARCH_CACHE_MAX_ENTRIES", "2")
    get_settings.cache_clear()
    calls = install(monkeypatch, photon=[photon_feature("X", 110.4, -7.7)])

    def photon_calls():
        return len([c for c in calls if c["service"] == "photon"])

    search("aaa kopi", 3)
    search("bbb kopi", 3)
    search("aaa kopi", 3)  # menyentuh 'aaa': kini 'bbb' yang paling lama tidak dipakai
    search("ccc kopi", 3)  # menyingkirkan 'bbb', bukan 'aaa'
    before = photon_calls()
    search("aaa kopi", 3)
    assert photon_calls() == before  # 'aaa' masih di cache
    search("bbb kopi", 3)
    assert photon_calls() == before + 1  # 'bbb' sudah tersingkir -> panggil lagi


def test_cache_expires_after_the_configured_ttl(monkeypatch):
    monkeypatch.setenv("GEO_SEARCH_CACHE_SECONDS", "0")
    get_settings.cache_clear()
    calls = install(monkeypatch, photon=[photon_feature("X", 110.4, -7.7)])

    search("kopi kecil", 3)
    search("kopi kecil", 3)

    assert len([c for c in calls if c["service"] == "photon"]) == 2


def test_partial_results_from_a_failing_layer_are_not_cached(monkeypatch):
    calls = install(monkeypatch, mapbox_exc=httpx.ConnectTimeout("x"), photon=[])

    first = search("tempat jauh", 3)
    places._photon_down_until = 0.0
    search("tempat jauh", 3)

    assert first.degraded is True
    assert len([c for c in calls if c["service"] == "mapbox"]) == 2  # tidak di-cache: dicoba lagi


# ---------------------------------------------------------------------- resolver


def test_resolve_place_returns_the_top_valid_result_or_none(monkeypatch):
    install(monkeypatch, photon=[], mapbox=[])

    assert resolve_place("UGM") == (-7.7716, 110.3775)
    assert resolve_place("tempat tak ada sama sekali") is None
    assert resolve_place(" ") is None and resolve_place("a") is None


def test_resolver_falls_back_to_photon_and_wilayah_for_route_text(monkeypatch):
    install(monkeypatch, photon=[photon_feature("Kopi Klotok", 110.416, -7.685, osm_value="cafe")])
    assert resolve_place("kopi klotok") == (-7.685, 110.416)

    places.clear_place_cache()
    install(monkeypatch, photon=[])
    assert resolve_place("caturtunggal", DIRECTORY) == (-7.765, 110.38)  # lewat tabel areas (Photon kosong)


def test_keywords_never_appear_in_logs_at_any_level(monkeypatch, caplog):
    install(monkeypatch, photon_status=500, mapbox_status=500)

    with caplog.at_level(logging.DEBUG):
        search("rumah-RAHASIA-pak-budi", 5, DIRECTORY)
        resolve_place("rumah-RAHASIA-pak-budi", DIRECTORY)

    assert "RAHASIA" not in caplog.text and TOKEN not in caplog.text


def test_real_landmarks_file_has_only_utf8_json_with_the_documented_shape():
    data = json.loads(Path(LANDMARKS_PATH).read_text(encoding="utf-8"))

    assert data["versi"] == 1 and isinstance(data["catatan"], str) and isinstance(data["tempat"], list)
    assert {"nama", "alias", "kategori", "lat", "lon", "keyakinan"} == set(data["tempat"][0])


# ================================================================== nominatim (lapisan 3)


@pytest.fixture
def sleeps(monkeypatch):
    """Tangkap jeda pembatas laju Nominatim tanpa benar-benar tidur."""
    recorded: list[float] = []
    monkeypatch.setattr(places, "_sleep", recorded.append)
    return recorded


def test_nominatim_is_not_used_for_autocomplete_while_photon_works(monkeypatch):
    calls = install(monkeypatch, photon=[], nominatim=[nominatim_item("Kopi Klotok", 110.416, -7.685)])

    assert search("kopi klotok", 5).hits == ()  # autocomplete biasa: Photon sehat -> tidak menyentuh Nominatim
    assert not [c for c in calls if c["service"] == "nominatim"]


def test_final_text_resolution_uses_nominatim_after_photon_with_the_documented_request(monkeypatch, sleeps):
    calls = install(monkeypatch, photon=[], nominatim=[nominatim_item("Kopi Klotok", 110.416, -7.685, village="Pakem")])

    assert resolve_place("kopi klotok") == (-7.685, 110.416)

    assert [c["service"] for c in calls] == ["photon", "nominatim"]
    [call] = [c for c in calls if c["service"] == "nominatim"]
    assert call["params"]["q"] == "kopi klotok" and call["params"]["format"] == "jsonv2"
    assert call["params"]["countrycodes"] == "id" and call["params"]["bounded"] == 1
    assert call["params"]["viewbox"] == "110.0,-7.5,110.85,-8.25"  # kiri,atas,kanan,bawah (bbox DIY)
    assert "Gardu" in call["headers"]["User-Agent"] and call["timeout"] == 3.0
    assert sleeps == []  # permintaan pertama tidak menunggu


def test_nominatim_hit_fields_and_source(monkeypatch):
    install(monkeypatch, photon=[], nominatim=[nominatim_item("Kopi Klotok", 110.416, -7.685, village="Pakem")])

    [hit] = search("kopi klotok", 3, final=True).hits

    assert (hit.source, hit.label, hit.category) == ("nominatim", "Kopi Klotok", "cafe")
    assert hit.place_name == "Kopi Klotok, Pakem, Kabupaten Sleman" and (hit.latitude, hit.longitude) == (-7.685, 110.416)


def test_nominatim_results_are_filtered_to_diy(monkeypatch):
    install(monkeypatch, photon=[], nominatim=[
        nominatim_item("Kopi Klaten", 110.64, -7.70, state="Jawa Tengah", county="Kabupaten Klaten"),  # provinsi lain
        nominatim_item("Kopi Jakarta", 106.8, -6.2, state="DKI Jakarta"),  # di luar bbox
        {"lat": "-7.7", "lon": "110.4", "address": {"state": "Daerah Istimewa Yogyakarta"}},  # tanpa nama
        {"name": "rusak", "lat": "bukan-angka", "lon": "110.4"},
        "bukan objek",
        nominatim_item("Kopi Sleman", 110.40, -7.71),
    ])

    assert [h.label for h in search("kopi", 5, final=True).hits] == ["Kopi Sleman"]


def test_autocomplete_falls_back_to_nominatim_when_photon_is_down_without_waiting(monkeypatch, sleeps):
    calls = install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"),
                    nominatim=[nominatim_item("Kopi Klotok", 110.416, -7.685)], mapbox=[mapbox_feature("Kopi M", 110.4, -7.7)])

    first = search("kopi klotok", 3)
    second = search("kopi lain", 3)  # <1 dtk kemudian: giliran Nominatim belum tiba -> dilewati, TIDAK menunggu

    assert [h.source for h in first.hits] == ["nominatim"]  # cukup 1 hasil -> Mapbox tidak perlu dipanggil
    assert first.degraded is True
    assert len([c for c in calls if c["service"] == "nominatim"]) == 1
    assert [h.source for h in second.hits] == ["mapbox"] and second.degraded is True
    assert sleeps == []


def test_final_resolution_waits_for_its_turn_so_the_rate_never_exceeds_one_per_second(monkeypatch, sleeps):
    install(monkeypatch, photon=[], nominatim=[nominatim_item("Tempat Satu", 110.4, -7.7)])
    now = [100.0]
    monkeypatch.setattr(places.time, "monotonic", lambda: now[0])

    resolve_place("tempat satu")  # slot 100.0 -> slot berikutnya 101.0
    now[0] = 100.4
    resolve_place("tempat dua")  # harus menunggu 0.6 dtk

    assert len(sleeps) == 1 and sleeps[0] == pytest.approx(0.6)


def test_final_resolution_skips_nominatim_instead_of_queueing_past_the_max_wait(monkeypatch, sleeps):
    calls = install(monkeypatch, photon=[], nominatim=[nominatim_item("Tempat", 110.4, -7.7)],
                    mapbox=[mapbox_feature("Tempat M", 110.41, -7.71)])
    monkeypatch.setenv("GEO_NOMINATIM_MIN_INTERVAL_SECONDS", "10")
    get_settings.cache_clear()
    now = [50.0]
    monkeypatch.setattr(places.time, "monotonic", lambda: now[0])

    resolve_place("tempat satu")
    now[0] = 51.0  # giliran berikutnya 9 dtk lagi > batas tunggu 1.5 dtk
    assert resolve_place("tempat dua") == (-7.71, 110.41)  # jatuh ke Mapbox, bukan menunggu

    assert len([c for c in calls if c["service"] == "nominatim"]) == 1 and sleeps == []


def test_nominatim_results_are_cached_for_thirty_minutes_separately_from_search_results(monkeypatch, sleeps):
    calls = install(monkeypatch, photon=[], nominatim=[nominatim_item("Kopi Klotok", 110.416, -7.685)])

    resolve_place("kopi klotok")
    places._cache.clear()  # cache hasil gabungan 10 menit sudah lewat; cache Nominatim 30 menit belum
    resolve_place("Kopi  Klotok")

    assert len([c for c in calls if c["service"] == "nominatim"]) == 1
    assert get_settings().geo_nominatim_cache_seconds == 1800


def test_nominatim_failure_opens_a_cooldown_and_everything_else_still_answers(monkeypatch, sleeps):
    calls = install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"), nominatim_exc=httpx.ReadTimeout("x"),
                    mapbox=[mapbox_feature("Pasar Kranggan", 110.366, -7.779)])

    first = search("pasar kranggan", 3, DIRECTORY, final=True)
    second = search("pasar lain", 3, DIRECTORY, final=True)

    assert [h.source for h in first.hits] == ["mapbox"] and first.degraded is True
    assert len([c for c in calls if c["service"] == "nominatim"]) == 1  # kedua tidak mencoba lagi (jeda)
    assert second.degraded is True


@pytest.mark.parametrize("final", [False, True])
def test_photon_and_nominatim_both_down_still_fall_back_to_landmark_wilayah_and_mapbox_without_error(monkeypatch, sleeps, final):
    install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"), nominatim_exc=httpx.ConnectTimeout("x"),
            mapbox=[mapbox_feature("Pasar Kranggan", 110.366, -7.779)])

    assert search("UGM", 3, DIRECTORY, final=final).hits[0].source == "landmark"
    assert search("caturtunggal", 3, DIRECTORY, final=final).hits[0].source == "wilayah"
    assert search("pasar kranggan", 3, DIRECTORY, final=final).hits[0].source == "mapbox"
    install(monkeypatch, photon_exc=httpx.ConnectTimeout("x"), nominatim_exc=httpx.ConnectTimeout("x"), mapbox=[])
    assert search("tempat tak dikenal", 3, DIRECTORY, final=final).hits == ()  # semua habis: kosong, bukan error


def test_nominatim_can_be_switched_off(monkeypatch, sleeps):
    monkeypatch.setenv("GEO_NOMINATIM_ENABLED", "false")
    get_settings.cache_clear()
    calls = install(monkeypatch, photon=[], nominatim=[nominatim_item("X", 110.4, -7.7)], mapbox=[mapbox_feature("Kopi M", 110.4, -7.7)])

    assert [h.source for h in search("kopi", 3, final=True).hits] == ["mapbox"]
    assert not [c for c in calls if c["service"] == "nominatim"]


def test_nominatim_keywords_and_urls_never_appear_in_logs(monkeypatch, caplog, sleeps):
    install(monkeypatch, photon_status=500, nominatim_status=500, mapbox_status=500)

    with caplog.at_level(logging.DEBUG):
        search("rumah-RAHASIA-pak-budi", 5, DIRECTORY, final=True)

    assert "RAHASIA" not in caplog.text and TOKEN not in caplog.text and "nominatim.openstreetmap" not in caplog.text
