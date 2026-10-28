"""Fase F: demo_data.py — data demo realistis, bertanda jelas, idempoten, dan bisa dihapus bersih."""

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import pytest
from db_fake import FakeDb

from app.agents.incident_index import CATEGORY_RULES, IncidentIndex, IndexedIncident, normalize_category
from app.agents.risk_agent import TIME_BUCKET_HOURS, ScorableIncident, compute_risk_scores, time_bucket_of
from app.agents.route_analysis import analyze_route
from app.core.areas import in_diy
from app.core.config import get_settings
from app.core.directions import RouteGeometry
from app.core.timeutil import WIB
from app.scripts import demo_data
from app.scripts.demo_data import (
    BUCKET_HOURS,
    CORRIDOR_HOTSPOTS,
    DEMO_TAG,
    HOTSPOTS,
    apply_demo_data,
    build_demo_incidents,
    purge_demo_data,
)

TODAY = date(2026, 10, 28)
SETTINGS = get_settings()
VOCABULARY = {name for name, _ in CATEGORY_RULES} | {"lainnya"}
# Kata yang menandakan ciri/identitas individu atau institusi tertentu — tidak boleh ada di data demo.
IDENTITY_WORDS = re.compile(
    r"\b(nama|bernama|inisial|usia|tahun|siswa|siswi|mahasiswa|pelajar|korban|pelaku|sma|smp|smk|sekolah|kampus|universitas|"
    r"plat|nopol|nik|ktp)\b",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def incidents():
    return build_demo_incidents(TODAY)


# ============================================================== isi data (fungsi murni)


def test_demo_incidents_are_all_inside_diy_and_never_in_the_future(incidents):
    assert len(incidents) >= 90
    assert all(in_diy(i.latitude, i.longitude) for i in incidents)
    noon = datetime(TODAY.year, TODAY.month, TODAY.day, 23, 59, tzinfo=WIB)
    assert all(i.incident_time <= noon for i in incidents)
    assert all(timedelta(days=1) <= noon - i.incident_time <= timedelta(days=140) for i in incidents)


def test_every_row_is_unmistakably_marked_unique_and_never_a_seed_row(incidents):
    assert len({i.sumber for i in incidents}) == len(incidents)  # kunci upsert unik
    for incident in incidents:
        assert incident.sumber.startswith(DEMO_TAG) and "BUKAN kejadian nyata" in incident.sumber
        record = incident.as_record()
        assert record["is_seed_data"] is False and record["status"] == "terverifikasi"
        assert set(record) == {"location_text", "latitude", "longitude", "incident_time", "incident_type", "status", "is_seed_data", "sumber"}


def test_no_individual_identity_or_story_anywhere_and_types_come_from_the_fixed_vocabulary(incidents):
    for incident in incidents:
        text = " | ".join([incident.location_text, incident.incident_type, incident.sumber.replace(demo_data.DEMO_NOTE, "")])
        assert not IDENTITY_WORDS.search(text), text
        assert incident.incident_type in VOCABULARY
        assert normalize_category(incident.incident_type) == incident.incident_type  # ikut skor/rute tanpa berubah jadi "lainnya"


def test_all_five_time_buckets_are_covered_including_the_midday_ones_the_seed_data_lacks(incidents):
    assert Counter(i.bucket for i in incidents).keys() == {name for name, _s, _e in TIME_BUCKET_HOURS}
    assert all(i.bucket == time_bucket_of(i.incident_time) for i in incidents)
    for bucket, hours in BUCKET_HOURS.items():
        start, end = next((s, e) for name, s, e in TIME_BUCKET_HOURS if name == bucket)
        assert all(start <= h < end for h in hours), bucket


def test_cells_show_all_three_levels_overall_and_hot_and_warm_cells_exist_in_every_bucket(incidents):
    rows = compute_risk_scores([ScorableIncident(i.latitude, i.longitude, i.incident_time) for i in incidents],
                               datetime(TODAY.year, TODAY.month, TODAY.day, 12, tzinfo=WIB), SETTINGS)
    levels: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        levels[row.time_bucket][row.risk_level] += 1
    assert {lvl for c in levels.values() for lvl in c} == {"tinggi", "sedang", "rendah"}
    for bucket in BUCKET_HOURS:
        assert levels[bucket]["tinggi"] >= 1 and levels[bucket]["sedang"] >= 1, (bucket, levels[bucket])


def test_the_big_roads_the_route_check_should_show_are_all_represented():
    labels = " ".join(h.label for h in CORRIDOR_HOTSPOTS)
    for road in ("Kaliurang", "Ring Road Utara", "Ring Road Timur", "Parangtritis", "Magelang", "Solo", "Wonosari"):
        assert road in labels, road
    districts = {h.label for h in HOTSPOTS if h.label.startswith("Kecamatan")}
    assert len(districts) >= 12  # banyak kecamatan, di kelima kabupaten/kota


def test_generation_is_deterministic_and_moves_with_today():
    assert build_demo_incidents(TODAY) == build_demo_incidents(TODAY)
    later = build_demo_incidents(TODAY + timedelta(days=10))
    first, shifted = build_demo_incidents(TODAY), later
    assert [i.sumber for i in first] == [i.sumber for i in shifted]
    assert all(b.incident_time - a.incident_time == timedelta(days=10) for a, b in zip(first, shifted))


# ============================================ perilaku di Cek Rute (analisis rute sungguhan)


def _index(incidents) -> IncidentIndex:
    return IncidentIndex(
        [IndexedIncident(n, i.latitude, i.longitude, i.incident_time, i.bucket, normalize_category(i.incident_type))
         for n, i in enumerate(incidents)],
        cell_meters=SETTINGS.route_data_coverage_radius_meters,
    )


def _route_through(slugs: list[str]) -> RouteGeometry:
    by_slug = {h.slug: h for h in HOTSPOTS}
    points = tuple((by_slug[s].latitude, by_slug[s].longitude) for s in slugs)
    return RouteGeometry(points=points, distance_m=10_000.0, duration_s=1_200.0)


def _status(incidents, slugs, hour):
    when = datetime(TODAY.year, TODAY.month, TODAY.day, hour, 0, tzinfo=WIB) + timedelta(days=1)
    return analyze_route(_route_through(slugs), when, _index(incidents), SETTINGS).status


def test_route_check_over_the_demo_roads_gives_a_mix_of_safe_alert_and_high_risk(incidents):
    statuses = {
        ("kaliurang", "malam"): _status(incidents, ["kal-1", "kal-2", "kal-3"], 21),
        ("kaliurang", "siang"): _status(incidents, ["kal-1", "kal-2", "kal-3"], 12),
        ("parangtritis", "dini_hari"): _status(incidents, ["par-1", "par-2"], 2),
        ("parangtritis", "siang"): _status(incidents, ["par-1", "par-2"], 13),
        ("ring_road_utara", "dini_hari"): _status(incidents, ["rru-1", "rru-2"], 2),
        ("magelang", "malam"): _status(incidents, ["mag-1", "mag-2", "mag-3"], 21),
        ("solo", "sore"): _status(incidents, ["sol-1", "sol-2"], 17),
        ("wonosari", "malam"): _status(incidents, ["won-1", "won-2"], 21),
    }
    assert set(statuses.values()) == {"aman", "waspada", "berisiko_tinggi"}
    assert statuses[("kaliurang", "malam")] == "berisiko_tinggi" and statuses[("kaliurang", "siang")] == "aman"
    assert statuses[("parangtritis", "dini_hari")] == "berisiko_tinggi" and statuses[("parangtritis", "siang")] == "aman"
    assert statuses[("ring_road_utara", "dini_hari")] == "waspada"
    assert statuses[("solo", "sore")] == "waspada" and statuses[("wonosari", "malam")] == "waspada"


# ======================================================================= database


def _db():
    seed = {"id": "seed-1", "is_seed_data": True, "status": "baru", "sumber": "Detik.com — contoh", "location_text": "Seed"}
    community = {"id": "kom-1", "is_seed_data": False, "status": "terverifikasi", "sumber": None, "location_text": "Komunitas"}
    trap = {"id": "seed-trap", "is_seed_data": True, "status": "baru", "sumber": f"{DEMO_TAG} salah satu seed", "location_text": "Jebakan"}
    return FakeDb(incidents=[seed, community, trap])


def _non_demo_ids(db):
    return {r["id"] for r in db.rows("incidents") if r["id"] in {"seed-1", "kom-1", "seed-trap"}}


def test_apply_inserts_every_demo_row_and_never_touches_seed_or_community_rows(incidents):
    db = _db()

    result = apply_demo_data(db, incidents)

    assert (result.inserted, result.updated, result.removed) == (len(incidents), 0, 0)
    demo_rows = [r for r in db.rows("incidents") if str(r.get("sumber")).startswith(DEMO_TAG) and not r["is_seed_data"]]
    assert len(demo_rows) == len(incidents)
    assert _non_demo_ids(db) == {"seed-1", "kom-1", "seed-trap"}
    assert db.row("incidents", "seed-1")["sumber"] == "Detik.com — contoh"


def test_apply_is_idempotent_and_refreshes_times_when_run_on_another_day(incidents):
    db = _db()
    apply_demo_data(db, incidents)
    before = {r["sumber"]: r["incident_time"] for r in db.rows("incidents") if r["sumber"] and r["sumber"].startswith(DEMO_TAG) and not r["is_seed_data"]}

    second = apply_demo_data(db, build_demo_incidents(TODAY + timedelta(days=3)))

    assert (second.inserted, second.updated, second.removed) == (0, len(incidents), 0)
    after = {r["sumber"]: r["incident_time"] for r in db.rows("incidents") if r["sumber"] and r["sumber"].startswith(DEMO_TAG) and not r["is_seed_data"]}
    assert len(after) == len(before) == len(incidents) and after != before  # tidak menggandakan, waktunya disegarkan
    assert len(db.rows("incidents")) == len(incidents) + 3


def test_apply_removes_obsolete_demo_rows_but_not_a_seed_row_that_merely_mentions_the_tag(incidents):
    db = _db()
    db.rows("incidents").append({"id": "usang", "is_seed_data": False, "status": "terverifikasi", "sumber": f"{DEMO_TAG} hotspot-lama-01 — x"})

    result = apply_demo_data(db, incidents)

    assert result.removed == 1
    assert "usang" not in {r["id"] for r in db.rows("incidents")} and "seed-trap" in {r["id"] for r in db.rows("incidents")}


def test_purge_removes_only_demo_rows_and_reports_the_count(incidents):
    db = _db()
    apply_demo_data(db, incidents)

    removed = purge_demo_data(db)

    assert removed == len(incidents)
    assert {r["id"] for r in db.rows("incidents")} == {"seed-1", "kom-1", "seed-trap"}
    assert purge_demo_data(db) == 0  # idempoten


# ================================================================== CLI


@pytest.fixture
def cli(monkeypatch):
    db = _db()
    recalcs: list[str] = []
    monkeypatch.setattr(demo_data, "get_supabase", lambda: db)
    monkeypatch.setattr(demo_data, "_recalculate", lambda: recalcs.append("hitung"))
    return db, recalcs


def test_writing_requires_the_explicit_confirm_flag_and_otherwise_writes_nothing(cli):
    db, recalcs = cli

    assert demo_data.main([]) == 2
    assert db.writes() == [] and recalcs == []


def test_dry_run_writes_nothing_and_prints_a_preview(cli, caplog):
    db, recalcs = cli
    caplog.set_level("INFO")
    db.rows("incidents").clear()  # tabel kosong: pratinjau tetap jalan dengan data demo saja

    assert demo_data.main(["--dry-run"]) == 0

    assert db.writes() == [] and recalcs == []
    assert "Pratinjau sel skor per bucket" in caplog.text and "siang" in caplog.text and "sore" in caplog.text


def test_confirmed_run_writes_then_recalculates_scores_unless_told_not_to(cli):
    db, recalcs = cli

    assert demo_data.main(["--confirm-demo"]) == 0
    assert recalcs == ["hitung"] and len(db.rows("incidents")) > 100

    assert demo_data.main(["--confirm-demo", "--no-recalculate"]) == 0
    assert recalcs == ["hitung"]


def test_purge_cli_removes_demo_rows_and_recalculates(cli):
    db, recalcs = cli
    demo_data.main(["--confirm-demo", "--no-recalculate"])

    assert demo_data.main(["--purge"]) == 0

    assert {r["id"] for r in db.rows("incidents")} == {"seed-1", "kom-1", "seed-trap"} and recalcs == ["hitung"]
    with pytest.raises(SystemExit):
        demo_data.main(["--purge", "--dry-run"])


def test_database_failure_is_exit_1_without_leaking_details(cli, capsys, caplog):
    db, _ = cli
    db.fail_on[("incidents", "select")] = True

    assert demo_data.main(["--confirm-demo"]) == 1
    assert "database mati" not in capsys.readouterr().out + caplog.text
