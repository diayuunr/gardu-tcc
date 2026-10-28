"""Fase F: demo_scenario.py — skenario "lapor -> terverifikasi -> skor naik" lewat API publik (di sini API palsu)."""

import json
import re
from datetime import datetime

import httpx
import pytest
from db_fake import FakeDb

from app.scripts import demo_scenario
from app.scripts.demo_scenario import (
    PLACES,
    SCENARIO,
    SCENARIO_TAG,
    Region,
    ScenarioError,
    cleanup_scenario,
    read_statuses,
    resolve_region,
    run_scenario,
)
from app.core.timeutil import WIB

NOW = datetime(2026, 10, 28, 20, 0, tzinfo=WIB)
AREAS = {
    ("kabkota", None): [
        {"kode": "34.04", "nama": "Kabupaten Sleman", "tingkat": "kabkota", "parent_kode": None, "latitude": -7.7, "longitude": 110.3},
        {"kode": "34.71", "nama": "Kota Yogyakarta", "tingkat": "kabkota", "parent_kode": None, "latitude": -7.8, "longitude": 110.37},
    ],
    ("kecamatan", "34.04"): [{"kode": "34.04.06", "nama": "Depok", "tingkat": "kecamatan", "parent_kode": "34.04", "latitude": -7.77, "longitude": 110.41}],
    ("kecamatan", "34.71"): [{"kode": "34.71.03", "nama": "Gondokusuman", "tingkat": "kecamatan", "parent_kode": "34.71", "latitude": -7.78, "longitude": 110.38}],
    ("kelurahan", "34.04.06"): [
        {"kode": "34.04.06.2002", "nama": "Condongcatur", "tingkat": "kelurahan", "parent_kode": "34.04.06", "latitude": -7.75, "longitude": 110.4},
        {"kode": "34.04.06.2001", "nama": "Caturtunggal", "tingkat": "kelurahan", "parent_kode": "34.04.06", "latitude": -7.771, "longitude": 110.387},
    ],
    ("kelurahan", "34.71.03"): [{"kode": "34.71.03.1001", "nama": "Kotabaru", "tingkat": "kelurahan", "parent_kode": "34.71.03", "latitude": None, "longitude": None}],
}


class FakeBackend:
    """Backend palsu di balik httpx.MockTransport. `verify_after` = berapa kali status dibaca sebelum A1-A3 terverifikasi."""

    def __init__(self, *, healthy=True, rate_limited=False, reject=False, baseline=0.0, raised=3.1):
        self.healthy, self.rate_limited, self.reject = healthy, rate_limited, reject
        self.posted: list[dict] = []
        self.score_calls = 0
        self.baseline, self.raised = baseline, raised
        self.verified = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200 if self.healthy else 503, json={"status": "ok"})
        if path == "/areas":
            params = request.url.params
            return httpx.Response(200, json={"count": 1, "areas": AREAS[(params["tingkat"], params.get("parent"))]})
        if path == "/risk/score":
            self.score_calls += 1
            value = self.raised if self.verified else self.baseline
            return httpx.Response(200, json={"risk_score": value, "risk_level": "sedang" if value >= 3 else "rendah",
                                             "contributing_incident_count": 1 if self.verified else 0, "label": "Kec. Depok"})
        if path == "/reports":
            if self.rate_limited:
                return httpx.Response(429, json={"detail": "Terlalu banyak laporan"})
            if self.reject:
                return httpx.Response(422, json={"detail": "Input tidak valid"})
            payload = json.loads(request.content)
            self.posted.append(payload)
            return httpx.Response(201, json={"id": f"id-{len(self.posted)}", "status": "menunggu_verifikasi", "created_at": "2026-10-28T13:00:00+00:00"})
        return httpx.Response(404, json={"detail": "x"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://testserver")  # host yang diizinkan conftest; transport palsu, tanpa jaringan


class Timeline:
    """Pembaca status palsu: sesudah `after` pembacaan, A1-A3 menjadi terverifikasi (insiden terverifikasi)."""

    def __init__(self, backend: FakeBackend, after: int, b1_processed: bool = True):
        self.backend, self.after, self.reads, self.b1_processed = backend, after, 0, b1_processed

    def __call__(self, ids: list[str]) -> dict[str, dict]:
        self.reads += 1
        done = self.reads > self.after
        self.backend.verified = done
        result = {}
        for n, report_id in enumerate(ids):
            twin = n < 3
            result[report_id] = {
                "status": "terverifikasi" if twin and done else "menunggu_verifikasi",
                "incident_id": "inc-1" if twin and done else ("inc-2" if self.b1_processed and not twin else None),
                "incident_status": ("terverifikasi" if done else "baru") if twin else ("baru" if self.b1_processed else None),
            }
        return result


class Clock:
    """Waktu palsu: tiap sleep memajukan jam."""

    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _run(backend, timeline, **kwargs):
    clock, lines = Clock(), []
    ok = run_scenario(backend.client(), timeline, now=NOW, sleep=clock.sleep, clock=clock, out=lines.append, **kwargs)
    return ok, "\n".join(lines), clock


# ============================================================ isi skenario


def test_the_scenario_has_three_twin_reports_and_one_lone_report_and_every_text_is_tagged_and_anonymous():
    assert [s.key for s in SCENARIO] == ["A1", "A2", "A3", "B1"]
    assert [s.place for s in SCENARIO] == ["A", "A", "A", "B"]
    assert len({s.text for s in SCENARIO}) == 4  # bukan salinan: bukan duplikat
    for scenario in SCENARIO:
        assert scenario.text.startswith(SCENARIO_TAG) and 10 <= len(scenario.text) <= 2000
        assert not re.search(r"\b(nama|bernama|inisial|usia|\d{2} tahun|plat|nopol|ktp)\b", scenario.text, re.IGNORECASE)
    assert set(PLACES) == {"A", "B"}


# =========================================================== wilayah berjenjang


def test_region_is_resolved_down_the_dropdown_chain_using_real_codes_and_prefers_the_named_kelurahan():
    client = FakeBackend().client()

    region = resolve_region(client, PLACES["A"])

    assert (region.kabkota_kode, region.kecamatan_kode, region.kelurahan_kode) == ("34.04", "34.04.06", "34.04.06.2001")
    assert region.label == "Caturtunggal, Depok, Kabupaten Sleman" and (region.latitude, region.longitude) == (-7.771, 110.387)


def test_without_a_named_kelurahan_or_its_coordinates_the_kecamatan_centre_is_used():
    region = resolve_region(FakeBackend().client(), {"kabkota": "yogyakarta", "kecamatan": "gondokusuman", "kelurahan": "kotabaru"})

    assert region.kelurahan_kode == "34.71.03.1001" and (region.latitude, region.longitude) == (-7.78, 110.38)  # titik kelurahan null -> pusat kecamatan


def test_unknown_region_names_give_a_clear_error():
    with pytest.raises(ScenarioError, match="tidak ditemukan"):
        resolve_region(FakeBackend().client(), {"kabkota": "atlantis", "kecamatan": "x", "kelurahan": None})
    with pytest.raises(ScenarioError, match="Kecamatan 'zzz'"):
        resolve_region(FakeBackend().client(), {"kabkota": "sleman", "kecamatan": "zzz", "kelurahan": None})


# ============================================================ alur lengkap


def test_happy_path_posts_four_hierarchical_reports_waits_for_verification_and_sees_the_score_rise():
    backend = FakeBackend(baseline=0.0, raised=3.1)

    ok, output, _ = _run(backend, Timeline(backend, after=2))

    assert ok is True
    assert len(backend.posted) == 4
    for payload, scenario in zip(backend.posted, SCENARIO):
        assert payload["description"] == scenario.text
        assert payload["kabkota_kode"] and payload["kecamatan_kode"] and "location_text" not in payload  # jalur berjenjang
    assert backend.posted[0]["kelurahan_kode"] == "34.04.06.2001" and backend.posted[3]["kecamatan_kode"] == "34.71.03"
    assert all(datetime.fromisoformat(p["occurred_at"]) < NOW for p in backend.posted)
    assert "Skor SEBELUM" in output and "Skor SESUDAH: 3.10 (sedang" in output
    assert "terverifikasi : YA" in output and "Skor area A naik                   : YA" in output
    assert "B1: menunggu_verifikasi" in output  # laporan tunggal tetap menunggu


def test_status_lines_are_printed_only_when_something_changes():
    backend = FakeBackend()

    _, output, _ = _run(backend, Timeline(backend, after=3))

    status_lines = [line for line in output.splitlines() if line.startswith("  A1:")]
    assert len(status_lines) == 2  # menunggu -> terverifikasi (pembacaan identik tidak dicetak ulang)


def test_when_verification_never_finishes_it_stops_at_the_timeout_and_says_so():
    backend = FakeBackend()

    ok, output, clock = _run(backend, Timeline(backend, after=10**9), timeout_seconds=12)

    assert ok is False and "batas waktu tercapai" in output and "BELUM" in output
    assert 12 <= clock.now < 12 + 10  # tidak menunggu tanpa akhir


def test_score_that_does_not_rise_within_the_wait_is_reported_honestly():
    backend = FakeBackend(baseline=2.0, raised=2.0)

    ok, output, _ = _run(backend, Timeline(backend, after=1), score_wait_seconds=9)

    assert ok is False and "TIDAK TERLIHAT" in output and "cache peta" in output


def test_rate_limit_and_server_rejection_stop_the_scenario_with_a_clear_message():
    with pytest.raises(ScenarioError, match="429"):
        _run(FakeBackend(rate_limited=True), lambda ids: {})
    with pytest.raises(ScenarioError, match="HTTP 422"):
        _run(FakeBackend(reject=True), lambda ids: {})


def test_an_unhealthy_backend_is_reported_before_anything_is_sent():
    backend = FakeBackend(healthy=False)

    with pytest.raises(ScenarioError, match="tidak sehat"):
        _run(backend, lambda ids: {})

    assert backend.posted == []


# ======================================================== status dari database


def test_statuses_are_read_straight_from_the_database_with_the_incident_status():
    db = FakeDb(
        reports=[{"id": "r1", "status": "terverifikasi", "incident_id": "i1"}, {"id": "r2", "status": "menunggu_verifikasi", "incident_id": None}],
        incidents=[{"id": "i1", "status": "terverifikasi"}],
    )

    states = read_statuses(db, ["r1", "r2"])

    assert states["r1"] == {"status": "terverifikasi", "incident_id": "i1", "incident_status": "terverifikasi"}
    assert states["r2"]["incident_status"] is None


# ============================================================= pembersihan


def test_cleanup_removes_only_scenario_reports_and_the_incidents_that_become_empty():
    db = FakeDb(
        reports=[
            {"id": "s1", "description": f"{SCENARIO_TAG} satu", "incident_id": "inc-skenario"},
            {"id": "s2", "description": f"{SCENARIO_TAG} dua", "incident_id": "inc-skenario"},
            {"id": "s3", "description": f"{SCENARIO_TAG} tiga", "incident_id": "inc-bersama"},
            {"id": "real", "description": "Laporan warga sungguhan tentang kejadian", "incident_id": "inc-bersama"},
            {"id": "lone", "description": "Laporan lain tanpa insiden", "incident_id": None},
        ],
        incidents=[
            {"id": "inc-skenario", "is_seed_data": False, "status": "terverifikasi"},
            {"id": "inc-bersama", "is_seed_data": False, "status": "terverifikasi"},
            {"id": "seed", "is_seed_data": True, "status": "baru"},
        ],
    )

    reports, incidents = cleanup_scenario(db)

    assert (reports, incidents) == (3, 1)
    assert {r["id"] for r in db.rows("reports")} == {"real", "lone"}
    assert {r["id"] for r in db.rows("incidents")} == {"inc-bersama", "seed"}  # insiden yang masih punya laporan sungguhan tetap
    assert cleanup_scenario(db) == (0, 0)  # idempoten


def test_cleanup_never_deletes_a_seed_incident_even_if_a_scenario_report_points_at_it():
    db = FakeDb(
        reports=[{"id": "s1", "description": f"{SCENARIO_TAG} satu", "incident_id": "seed"}],
        incidents=[{"id": "seed", "is_seed_data": True, "status": "baru"}],
    )

    cleanup_scenario(db)

    assert [r["id"] for r in db.rows("incidents")] == ["seed"]


# ==================================================================== CLI


def test_cli_cleanup_deletes_and_recalculates_only_when_something_was_removed(monkeypatch, capsys):
    db = FakeDb(reports=[{"id": "s1", "description": f"{SCENARIO_TAG} satu", "incident_id": None}])
    monkeypatch.setattr(demo_scenario, "get_supabase", lambda: db)
    calls = []
    monkeypatch.setattr(demo_scenario, "recalculate_risk_scores", lambda: calls.append("hitung") or type("R", (), {"upserted": 1, "deleted": 0})())

    assert demo_scenario.main(["--cleanup"]) == 0
    assert demo_scenario.main(["--cleanup"]) == 0

    assert calls == ["hitung"]  # kali kedua tidak ada yang dihapus -> tidak menghitung ulang
    assert "Dihapus: 1 laporan skenario" in capsys.readouterr().out


def test_cli_reports_an_unreachable_backend_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr(demo_scenario, "get_supabase", lambda: FakeDb())

    def unreachable(*_a, **_k):
        raise httpx.ConnectError("tidak terjangkau (simulasi)")

    monkeypatch.setattr(demo_scenario, "run_scenario", unreachable)

    code = demo_scenario.main(["--base-url", "http://127.0.0.1:1"])

    assert code == 3 and "tidak terjangkau" in capsys.readouterr().err
