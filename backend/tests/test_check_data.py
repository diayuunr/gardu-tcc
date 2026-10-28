"""Fase F: check_data.py — laporan jumlah dan anomali; BACA-SAJA."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from db_fake import FakeDb

from app.core.areas import Area, AreaDirectory
from app.core.config import get_settings
from app.scripts import check_data
from app.scripts.check_data import BUCKETS, classify_incident, collect, render

NOW = datetime(2026, 10, 28, 5, 0, tzinfo=timezone.utc)
DIRECTORY = AreaDirectory([
    Area("34.04", "Kabupaten Sleman", "kabkota", None, -7.716, 110.3557),
    Area("34.04.06", "Depok", "kecamatan", "34.04", -7.7669, 110.4108),
    Area("34.71", "Kota Yogyakarta", "kabkota", None, -7.7956, 110.3695),
    Area("34.71.03", "Gondokusuman", "kecamatan", "34.71", -7.7828, 110.3822),
    Area("34.71.04", "Danurejan", "kecamatan", "34.71", -7.7932, 110.3722),
])


def _incident(ident, *, kind="seed", lat=-7.7669, lon=110.4108, status="baru", time="2026-03-01T15:00:00+00:00", sumber=None, **extra):
    row = {"id": ident, "latitude": lat, "longitude": lon, "incident_time": time, "status": status, "is_seed_data": kind == "seed"}
    row["sumber"] = sumber if sumber is not None else {"seed": "Detik.com — contoh", "demo": "[DEMO] kal-1-01 — BUKAN kejadian nyata", "komunitas": None}[kind]
    row.update(extra)
    return row


def _report(ident, status="terverifikasi", incident_id=None, lat=-7.77, lon=110.41):
    return {"id": ident, "status": status, "incident_id": incident_id, "latitude": lat, "longitude": lon}


def _score(area, bucket, level="rendah", place="Kec. Depok", at="2026-10-28T03:00:00+00:00"):
    return {"id": f"{area}-{bucket}", "area_name": area, "time_bucket": bucket, "risk_level": level, "place_name": place, "last_calculated_at": at}


def _healthy_scores():
    return [_score(f"A{n}", bucket) for n, bucket in enumerate(BUCKETS)]


def _run(db, **overrides):
    kwargs = dict(
        directory=DIRECTORY, now=NOW, settings=get_settings(),
        find_unfinished=lambda *_a: [], recalculate=None,
    )
    kwargs.update(overrides)
    return collect(db, **kwargs)


def _codes(report):
    return {f.code for f in report.findings}


def _db(incidents=(), reports=(), scores=None):
    db = FakeDb(incidents=list(incidents), reports=list(reports))
    db.tables["risk_scores"].rows[:] = _healthy_scores() if scores is None else scores
    return db


# ================================================================== penghitungan


def test_classification_separates_seed_demo_and_community_rows():
    assert classify_incident(_incident("a", kind="seed")) == "seed"
    assert classify_incident(_incident("b", kind="demo")) == "demo"
    assert classify_incident(_incident("c", kind="komunitas")) == "komunitas"
    # baris seed yang kebetulan memuat tag demo tetap seed (tak pernah dianggap demo)
    assert classify_incident(_incident("d", kind="seed", sumber="[DEMO] jebakan")) == "seed"


def test_counts_incidents_by_class_and_status_and_the_coordinates_gap():
    db = _db([
        _incident("s1"), _incident("s2", sumber="X [PERKIRAAN] waktu"), _incident("d1", kind="demo", status="terverifikasi"),
        _incident("k1", kind="komunitas", status="terverifikasi"), _incident("k2", kind="komunitas", status="baru", lat=None, lon=None),
    ], reports=[_report("r1", incident_id="k1"), _report("r2", incident_id="k2")])

    report = _run(db)

    assert report.incidents["total"] == 5 and report.incidents["seed"] == 2 and report.incidents["demo"] == 1
    assert report.incidents["komunitas"] == 2 and report.incidents["komunitas_baru"] == 1 and report.incidents["komunitas_terverifikasi"] == 1
    assert report.incidents["tanpa_koordinat"] == {"seed": 0, "demo": 0, "komunitas": 1}
    assert report.incidents["seed_perkiraan_waktu"] == 1
    assert "insiden_komunitas_tanpa_koordinat" in _codes(report)


def test_scores_are_counted_per_bucket_and_level_and_empty_buckets_are_called_out():
    scores = [_score("A", "dini_hari", "tinggi"), _score("B", "dini_hari", "rendah"), _score("C", "malam", "sedang")]
    report = _run(_db([_incident("s1")], scores=scores))

    per = report.scores["per_bucket"]
    assert per["dini_hari"] == {"total": 2, "tinggi": 1, "sedang": 0, "rendah": 1}
    assert per["siang"]["total"] == 0 and per["sore"]["total"] == 0
    [message] = [f.message for f in report.findings if f.code == "bucket_kosong"]
    assert "pagi" in message and "siang" in message and "sore" in message


def test_kecamatan_coverage_counts_districts_with_incidents_and_with_scores():
    db = _db([_incident("s1", lat=-7.7669, lon=110.4108), _incident("s2", lat=-7.7828, lon=110.3822)],
             scores=[_score("A", "malam", place="Kec. Depok"), _score("B", "malam", place="Kec. Depok"), _score("C", "pagi", place="Kec. Danurejan")])

    report = _run(db)

    assert report.coverage == {"kecamatan_total": 3, "kecamatan_dengan_insiden": 2, "kecamatan_dengan_skor": 2}


def test_reports_are_counted_by_status_with_orphans_from_the_reprocess_finder():
    db = _db([_incident("s1")], reports=[_report("r1", "menunggu_verifikasi"), _report("r2", "terverifikasi"), _report("r3", "menunggu_verifikasi", lat=None, lon=None)])

    report = _run(db, find_unfinished=lambda _db, _limit, _cutoff: ["r1", "r3"])

    assert report.reports["per_status"] == {"menunggu_verifikasi": 2, "terverifikasi": 1}
    assert report.reports["yatim"] == 2 and report.reports["tanpa_koordinat"] == 1
    assert "laporan_yatim" in _codes(report)


def test_orphan_finder_receives_the_configured_minimum_age():
    seen = {}

    def finder(_db, limit, cutoff):
        seen.update(limit=limit, cutoff=cutoff)
        return []

    _run(_db([_incident("s1")]), find_unfinished=finder)

    assert seen["cutoff"] == NOW - timedelta(minutes=get_settings().reprocess_min_age_minutes)


# =================================================================== anomali


def test_a_healthy_dataset_has_no_warnings():
    db = _db([_incident("s1"), _incident("k1", kind="komunitas", status="terverifikasi")], reports=[_report("r1", incident_id="k1"), _report("r2", incident_id="k1")])

    report = _run(db)

    assert report.warnings == []
    assert render(report)[-1] == "Tidak ada anomali."


@pytest.mark.parametrize(
    ("code", "incidents", "reports", "scores"),
    [
        ("tidak_ada_insiden", [], [], None),
        ("insiden_di_luar_diy", [_incident("s1", lat=-6.2, lon=106.8)], [], None),
        ("seed_tanpa_sumber", [_incident("s1", sumber="  ")], [], None),
        ("insiden_di_masa_depan", [_incident("s1", time="2027-01-01T00:00:00+00:00")], [], None),
        ("skor_kosong", [_incident("s1")], [], []),
        ("skor_tanpa_nama_wilayah", [_incident("s1")], [], [{**_score("A", b), "place_name": None} for b in BUCKETS]),
        ("skor_usang", [_incident("s1")], [], [_score(f"A{n}", b, at="2026-10-01T00:00:00+00:00") for n, b in enumerate(BUCKETS)]),
        ("laporan_mengacu_insiden_hilang", [_incident("s1")], [_report("r1", incident_id="hilang")], None),
        ("laporan_ditandai_punya_insiden", [_incident("k1", kind="komunitas", status="baru")], [_report("r1", "ditandai_hoaks", "k1")], None),
        ("insiden_terverifikasi_tanpa_laporan", [_incident("k1", kind="komunitas", status="terverifikasi")], [], None),
        ("insiden_belum_dipromosikan", [_incident("k1", kind="komunitas", status="baru")], [_report("r1", "menunggu_verifikasi", "k1"), _report("r2", "menunggu_verifikasi", "k1")], None),
        ("insiden_komunitas_tanpa_laporan", [_incident("k1", kind="komunitas", status="baru")], [], None),
    ],
)
def test_each_anomaly_is_reported_under_its_own_code(code, incidents, reports, scores):
    report = _run(_db(incidents, reports, scores))

    assert code in _codes(report)


def test_demo_rows_are_an_info_reminder_not_a_warning_and_are_not_flagged_as_report_less_incidents():
    report = _run(_db([_incident("d1", kind="demo", status="terverifikasi")]))

    assert "ada_data_demo" in _codes(report)
    assert report.warnings == []  # hanya pengingat info; bukan peringatan
    assert [f.severity for f in report.findings if f.code == "ada_data_demo"] == ["info"]
    assert "insiden_terverifikasi_tanpa_laporan" not in _codes(report) and "insiden_komunitas_tanpa_laporan" not in _codes(report)


def test_stored_scores_are_compared_with_a_fresh_calculation():
    db = _db([_incident("s1")], scores=[_score("A0", "dini_hari"), _score("OLD", "malam")])
    fresh = SimpleNamespace(rows=[SimpleNamespace(area_name="A0", time_bucket="dini_hari"), SimpleNamespace(area_name="NEW", time_bucket="pagi")])

    report = _run(db, recalculate=lambda **_kw: fresh)

    assert report.scores["sinkron_dengan_insiden"] is False and "skor_tidak_sinkron" in _codes(report)
    in_sync = _run(db, recalculate=lambda **_kw: SimpleNamespace(rows=[SimpleNamespace(area_name="A0", time_bucket="dini_hari"), SimpleNamespace(area_name="OLD", time_bucket="malam")]))
    assert in_sync.scores["sinkron_dengan_insiden"] is True and "skor_tidak_sinkron" not in _codes(in_sync)


def test_a_failing_recalculation_or_orphan_search_is_an_info_not_a_crash():
    def boom(*_a, **_k):
        raise RuntimeError("database mati (simulasi)")

    report = _run(_db([_incident("s1")]), recalculate=boom, find_unfinished=boom)

    assert {"perbandingan_skor_dilewati", "yatim_dilewati"} <= _codes(report)
    assert all(f.severity == "info" for f in report.findings if f.code in {"perbandingan_skor_dilewati", "yatim_dilewati"})


def test_without_area_data_coverage_is_skipped_with_an_info():
    report = _run(_db([_incident("s1")]), directory=None)

    assert report.coverage == {"kecamatan_total": None} and "tanpa_data_wilayah" in _codes(report)


def test_the_check_never_writes_anything():
    db = _db([_incident("s1"), _incident("k1", kind="komunitas", status="terverifikasi")], reports=[_report("r1", incident_id="k1")])

    _run(db)

    assert db.writes() == []


# ====================================================================== CLI


def _patch_cli(monkeypatch, db):
    monkeypatch.setattr(check_data, "get_supabase", lambda: db)
    monkeypatch.setattr(check_data, "get_directory_or_none", lambda _db: DIRECTORY)
    monkeypatch.setattr(check_data, "find_unfinished_reports", lambda *_a: [])


def test_cli_prints_the_text_report_and_exits_zero_even_with_warnings(monkeypatch, capsys):
    _patch_cli(monkeypatch, _db([], scores=[]))

    code = check_data.main(["--skip-recalc-compare"])

    out = capsys.readouterr().out
    assert code == 0 and "== INSIDEN ==" in out and "[PERINGATAN]" in out and "== TEMUAN ==" in out


def test_strict_mode_turns_warnings_into_exit_code_2_and_stays_zero_when_clean(monkeypatch, capsys):
    _patch_cli(monkeypatch, _db([], scores=[]))
    assert check_data.main(["--strict", "--skip-recalc-compare"]) == 2

    clean = _db([_incident("s1")])
    _patch_cli(monkeypatch, clean)
    assert check_data.main(["--strict", "--skip-recalc-compare"]) == 0


def test_json_output_is_valid_and_carries_the_findings(monkeypatch, capsys):
    _patch_cli(monkeypatch, _db([_incident("s1", lat=None, lon=None)]))

    assert check_data.main(["--json", "--skip-recalc-compare"]) == 0

    data = json.loads(capsys.readouterr().out)
    assert data["incidents"]["total"] == 1 and any(f["code"] == "insiden_seed_tanpa_koordinat" for f in data["findings"])


def test_cli_failure_is_exit_1_with_a_safe_message(monkeypatch, capsys):
    db = _db([_incident("s1")])
    db.fail_on[("incidents", "select")] = True
    _patch_cli(monkeypatch, db)

    assert check_data.main(["--skip-recalc-compare"]) == 1
    assert "database mati" not in capsys.readouterr().err
