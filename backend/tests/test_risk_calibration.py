"""Tes Tahap 2 Risk Prediction Agent: R1 kalibrasi, R2/R3 pengali musim saat baca,
R4 pelebaran antar sel, R5 pengaman hasil kosong, R6 dokumentasi bucket."""

import logging
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents import risk_agent
from app.agents.risk_agent import (
    TIME_BUCKET_HOURS,
    WIB,
    ScorableIncident,
    apply_seasonality,
    base_score_from_intensity,
    compute_risk_scores,
    fetch_risk_cells,
    locate_area,
    lookup_risk_score,
    recalculate_risk_scores,
    risk_level_for,
)
from app.agents.route_agent import CrossedCell, fetch_route_scores
from app.core.config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
POINT = (-7.812995, 110.39872)
CELL_DEGREES = 0.01
NORMAL_DAY = datetime(2026, 9, 20, 12, 0, tzinfo=WIB)
PRE_RAMADAN_DAY = datetime(2027, 1, 30, 12, 0, tzinfo=WIB)  # Ramadan 1448 H mulai 8 Feb 2027
DURING_RAMADAN_DAY = datetime(2027, 2, 20, 12, 0, tzinfo=WIB)
OWN_CELL = locate_area(*POINT, CELL_DEGREES)[2]


def _recent_incident(point=POINT, hours_before=0) -> ScorableIncident:
    """Insiden berbobot ~1 (baru saja terjadi) di jam 'malam'."""
    when = NORMAL_DAY.replace(hour=20) - timedelta(hours=hours_before)
    return ScorableIncident(latitude=point[0], longitude=point[1], incident_time=when)


def _compute(incidents, **overrides):
    settings = get_settings().model_copy(update=overrides)
    return compute_risk_scores(incidents, NORMAL_DAY.replace(hour=20), settings), settings


# ===================================================================== R1: kalibrasi


def test_default_saturation_scale_is_three_and_matches_the_documented_table():
    settings = get_settings()
    assert settings.risk_score_saturation_scale == 3.0

    expected = {1: (2.83, "rendah"), 2: (4.87, "sedang"), 3: (6.32, "sedang"), 4: (7.36, "tinggi"), 6: (8.65, "tinggi")}
    for incidents, (score, level) in expected.items():
        computed = base_score_from_intensity(float(incidents), settings)
        assert computed == pytest.approx(score, abs=0.005)
        assert risk_level_for(computed, settings) == level


def test_a_single_fresh_incident_is_not_medium_or_high_but_two_are_medium_and_four_high():
    def own_row(count):
        rows, _ = _compute([_recent_incident() for _ in range(count)])
        return next(r for r in rows if r.area_name == OWN_CELL)

    assert own_row(1).risk_level == "rendah"  # skala lama 1.0 menghasilkan 6.32 = sedang
    assert own_row(2).risk_level == "sedang"
    assert own_row(4).risk_level == "tinggi"


# ============================================ R2/R3: pengali musim diterapkan saat BACA


def test_apply_seasonality_multiplies_the_base_score_caps_at_ten_and_recomputes_the_level():
    settings = get_settings()

    normal = apply_seasonality(2.83, NORMAL_DAY.date(), "malam", settings)
    assert (normal.score, normal.level, normal.multiplier, normal.phase) == (2.83, "rendah", 1.0, None)

    pre = apply_seasonality(2.83, PRE_RAMADAN_DAY.date(), "malam", settings)
    assert pre.score == pytest.approx(3.68, abs=0.005) and pre.level == "sedang"  # level naik dari skor AKHIR
    assert pre.phase == "jelang_ramadan"

    sahur = apply_seasonality(9.0, DURING_RAMADAN_DAY.date(), "dini_hari", settings)  # 9.0 x 1.56 = 14.04
    assert sahur.score == 10.0 and sahur.level == "tinggi"  # dibatasi 10


def _score_row(**overrides):
    row = {
        "area_name": OWN_CELL, "time_bucket": "malam", "risk_score": 2.83, "risk_level": "rendah",
        "contributing_incident_count": 1, "latitude": -7.815, "longitude": 110.395,
        "last_calculated_at": "2026-09-20T05:00:00+00:00",
    }
    row.update(overrides)
    return row


class _Rows:
    """Supabase palsu: query chain apa pun berakhir di baris yang diberikan (filter in_/eq ikut diterapkan)."""

    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return _RowsQuery(self._rows)


class _RowsQuery:
    def __init__(self, rows):
        self._rows, self._filters, self._range = rows, [], None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append((column, {value}))
        return self

    def in_(self, column, values):
        self._filters.append((column, set(values)))
        return self

    def order(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r[c] in values for c, values in self._filters)]
        if self._range:
            rows = rows[self._range[0] : self._range[1] + 1]
        return SimpleNamespace(data=rows)


def test_same_stored_score_changes_level_when_the_date_enters_pre_ramadan_without_recalculating():
    fake = _Rows([_score_row()])

    evening = {"hour": 20}  # bucket "malam"
    normal = lookup_risk_score(fake, *POINT, NORMAL_DAY.replace(**evening))
    pre = lookup_risk_score(fake, *POINT, PRE_RAMADAN_DAY.replace(**evening))  # baris database TIDAK berubah

    assert (normal.risk_score, normal.risk_level) == (2.83, "rendah")
    assert pre.risk_score == pytest.approx(3.68, abs=0.005) and pre.risk_level == "sedang"
    assert pre.base_score == 2.83 and pre.season == "jelang_ramadan"
    assert pre.season_multiplier == get_settings().risk_ramadan_multiplier


def test_heatmap_cells_get_the_seasonal_multiplier_for_the_requested_date():
    fake = _Rows([_score_row(), _score_row(area_name="Area x", risk_score=9.0, risk_level="tinggi")])

    normal = {c.area_name: c for c in fetch_risk_cells(fake, "malam", date(2026, 9, 20))}
    ramadan = {c.area_name: c for c in fetch_risk_cells(fake, "malam", date(2027, 2, 20))}

    assert normal[OWN_CELL].risk_level == "rendah"
    assert ramadan[OWN_CELL].risk_level == "sedang"
    assert ramadan["Area x"].risk_score == 10.0  # 9.0 x 1.3 dibatasi 10
    assert ramadan[OWN_CELL].base_score == 2.83


def test_heatmap_defaults_to_today_wib(monkeypatch):
    fake = _Rows([_score_row()])
    monkeypatch.setattr(risk_agent, "today_wib", lambda: date(2027, 1, 30))

    assert fetch_risk_cells(fake, "malam")[0].risk_level == "sedang"


def test_route_scores_use_the_seasonal_multiplier_of_the_departure_date():
    cell = CrossedCell(OWN_CELL, -7.815, 110.395, "malam", 0.0)
    fake = _Rows([_score_row()])

    normal = fetch_route_scores(fake, [cell], date(2026, 9, 20))[(OWN_CELL, "malam")]
    pre = fetch_route_scores(fake, [cell], date(2027, 1, 30))[(OWN_CELL, "malam")]

    assert (normal.risk_score, normal.risk_level) == (2.83, "rendah")
    assert pre.risk_level == "sedang" and pre.risk_score == pytest.approx(3.68, abs=0.005)


def test_stored_scores_never_contain_the_seasonal_multiplier():
    def own_scores(as_of):
        # Umur insiden dibuat identik (1-3 jam sebelum as_of) supaya hanya musim yang berbeda.
        incidents = [ScorableIncident(*POINT, as_of - timedelta(hours=h)) for h in (1, 2, 3)]
        rows = compute_risk_scores(incidents, as_of, get_settings())
        return [r.risk_score for r in rows if r.area_name == OWN_CELL]

    out_of_season = own_scores(datetime(2026, 9, 20, 20, 0, tzinfo=WIB))
    in_season = own_scores(datetime(2027, 2, 20, 20, 0, tzinfo=WIB))  # selama Ramadan

    assert out_of_season and in_season == out_of_season


# ============================================================= R4: pelebaran antar sel


def _neighbour_point(d_row=0, d_col=1):
    """Titik di tengah sel tetangga."""
    lat, lon, _ = locate_area(*POINT, CELL_DEGREES)
    return lat + d_row * CELL_DEGREES, lon + d_col * CELL_DEGREES


def test_a_lone_incident_does_not_paint_neighbouring_cells():
    rows, _ = _compute([_recent_incident()])

    assert [r.area_name for r in rows] == [OWN_CELL]  # spill 0.25 -> skor 0.80 < ambang 1.0


def test_a_cluster_of_incidents_raises_neighbouring_cells_below_the_cells_own_score():
    rows, settings = _compute([_recent_incident() for _ in range(4)])

    by_area = {r.area_name: r for r in rows}
    assert len(by_area) == 9  # sel sendiri + 8 tetangga
    own = by_area[OWN_CELL]
    neighbour = by_area[locate_area(*_neighbour_point(0, 1), CELL_DEGREES)[2]]
    assert 0 < neighbour.risk_score < own.risk_score
    assert neighbour.contributing_incident_count == 0  # murni dari pengaruh tetangga
    assert own.contributing_incident_count == 4
    assert neighbour.risk_score == pytest.approx(
        base_score_from_intensity(4 * settings.risk_neighbor_weight, settings), abs=0.02
    )


def test_neighbour_weight_zero_turns_spreading_off():
    rows, _ = _compute([_recent_incident() for _ in range(4)], risk_neighbor_weight=0.0)

    assert [r.area_name for r in rows] == [OWN_CELL]


def test_neighbour_without_own_incidents_but_below_minimum_score_gets_no_row():
    rows, _ = _compute([_recent_incident() for _ in range(2)], risk_neighbor_min_score=2.0)

    assert [r.area_name for r in rows] == [OWN_CELL]  # spill 0.5 -> 1.53 < 2.0


def test_neighbour_with_its_own_incident_is_always_kept_and_receives_spill_from_both_sides():
    other = _neighbour_point(0, 1)
    rows, settings = _compute([_recent_incident(), _recent_incident(point=other)])

    by_area = {r.area_name: r for r in rows}
    other_cell = locate_area(*other, CELL_DEGREES)[2]
    assert {OWN_CELL, other_cell} <= set(by_area)
    # Masing-masing 1.0 sendiri + 0.25 dari tetangganya.
    assert by_area[OWN_CELL].risk_score == pytest.approx(base_score_from_intensity(1.25, settings), abs=0.02)
    assert by_area[OWN_CELL].contributing_incident_count == 1


# ================================================================ R5: pengaman hasil kosong


class _Resp:
    def __init__(self, data, count=None):
        self.data, self.count = data, count


class _Q:
    def __init__(self, table, op, payload=None):
        self._t, self._op, self._payload = table, op, payload
        self._eq, self._in, self._or, self._range, self._count = [], [], None, None, False

    def select(self, _cols, count=None):
        self._count = count == "exact"
        return self

    def or_(self, expression):
        self._or = [tuple(part.split(".eq.")) for part in expression.split(",")]
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        return self

    def in_(self, k, vs):
        self._in.append((k, list(vs)))
        return self

    def order(self, _c):
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def limit(self, _n):
        return self

    def _ok(self, row):
        if any(row.get(k) != v for k, v in self._eq) or any(row.get(k) not in vs for k, vs in self._in):
            return False
        coerce = {"true": True, "false": False}
        return not self._or or any(row.get(k) == coerce.get(v, v) for k, v in self._or)

    def execute(self):
        if self._t.fail:
            raise RuntimeError("koneksi database putus")
        rows = self._t.rows
        if self._op == "select":
            matched = [r for r in rows if self._ok(r)]
            total = len(matched)
            if self._range:
                matched = matched[self._range[0] : self._range[1] + 1]
            return _Resp(matched, count=total if self._count else None)
        if self._op == "upsert":
            for item in self._payload:
                existing = next((r for r in rows if (r["area_name"], r["time_bucket"]) == (item["area_name"], item["time_bucket"])), None)
                existing.update(item) if existing else rows.append({"id": str(uuid.uuid4()), **item})
            return _Resp(self._payload)
        if self._op == "delete":
            doomed = [r for r in rows if self._ok(r)]
            rows[:] = [r for r in rows if r not in doomed]
            return _Resp(doomed)
        raise AssertionError(self._op)


class _T:
    def __init__(self, rows, fail=False):
        self.rows, self.fail = rows, fail

    def select(self, cols, count=None):
        return _Q(self, "select").select(cols, count=count)

    def upsert(self, payload, on_conflict):
        return _Q(self, "upsert", payload)

    def delete(self):
        return _Q(self, "delete")


class _Db:
    def __init__(self, incidents, scores, fail_incidents=False):
        self.tables = {"incidents": _T(incidents, fail=fail_incidents), "risk_scores": _T(scores)}

    def table(self, name):
        return self.tables[name]


def _existing_scores():
    return [
        {"id": "s-1", "area_name": "Area lama 1", "time_bucket": "malam", "risk_score": 5.0, "risk_level": "sedang"},
        {"id": "s-2", "area_name": "Area lama 2", "time_bucket": "pagi", "risk_score": 8.0, "risk_level": "tinggi"},
    ]


def _incident_row(*, status="baru", seed=False, located=True):
    return {
        "id": str(uuid.uuid4()),
        "latitude": POINT[0] if located else None,
        "longitude": POINT[1] if located else None,
        "incident_time": datetime(2022, 4, 6, 22, 0, tzinfo=WIB).isoformat(),
        "is_seed_data": seed,
        "status": status,
    }


@pytest.mark.parametrize(
    "incidents",
    [
        [_incident_row(status="baru")],  # hanya insiden yang belum diverifikasi: tidak ada yang dinilai
        [_incident_row(seed=True, located=False)],  # semua tanpa koordinat
    ],
    ids=["hanya-insiden-baru", "tanpa-koordinat"],
)
def test_empty_result_with_non_empty_incidents_keeps_existing_scores_and_warns(incidents, caplog):
    db = _Db(incidents, _existing_scores())

    with caplog.at_level(logging.WARNING, logger="app.agents.risk_agent"):
        result = recalculate_risk_scores(NORMAL_DAY, supabase=db)

    assert result.blocked_empty is True
    assert (result.upserted, result.deleted) == (0, 0)
    assert [r["id"] for r in db.tables["risk_scores"].rows] == ["s-1", "s-2"]  # kode lama menghapus keduanya
    assert any("DIPERTAHANKAN" in record.getMessage() and "berisi 1 baris" in record.getMessage() for record in caplog.records)


def test_empty_result_because_there_are_truly_no_incidents_is_also_blocked_with_a_warning(caplog):
    db = _Db([], _existing_scores())

    with caplog.at_level(logging.WARNING, logger="app.agents.risk_agent"):
        result = recalculate_risk_scores(NORMAL_DAY, supabase=db)

    assert result.blocked_empty is True and len(db.tables["risk_scores"].rows) == 2
    assert any("tidak ada insiden sama sekali" in record.getMessage() for record in caplog.records)


def test_allow_empty_flag_explicitly_clears_the_scores():
    db = _Db([], _existing_scores())

    result = recalculate_risk_scores(NORMAL_DAY, supabase=db, allow_empty=True)

    assert result.blocked_empty is False and result.deleted == 2
    assert db.tables["risk_scores"].rows == []


def test_dry_run_with_empty_result_is_never_reported_as_blocked():
    db = _Db([], _existing_scores())

    result = recalculate_risk_scores(NORMAL_DAY, supabase=db, persist=False)

    assert result.blocked_empty is False and len(db.tables["risk_scores"].rows) == 2


def test_failed_incident_read_raises_and_never_touches_stored_scores():
    db = _Db([_incident_row(seed=True)], _existing_scores(), fail_incidents=True)

    with pytest.raises(RuntimeError):
        recalculate_risk_scores(NORMAL_DAY, supabase=db)

    assert [r["id"] for r in db.tables["risk_scores"].rows] == ["s-1", "s-2"]


def test_normal_non_empty_recalculation_still_replaces_stale_rows():
    db = _Db([_incident_row(seed=True)], _existing_scores())

    result = recalculate_risk_scores(NORMAL_DAY, supabase=db)

    assert result.blocked_empty is False and result.deleted == 2
    assert {r["area_name"] for r in db.tables["risk_scores"].rows} == {OWN_CELL}


# =================================================================== R6: dokumentasi bucket


def test_bucket_ranges_in_code_and_migration_comment_agree():
    comment = (MIGRATIONS / "20260921000200_risk_scores_column_comments.sql").read_text(encoding="utf-8")

    for bucket, start, end in TIME_BUCKET_HOURS:
        assert f"{bucket} {start:02d}-{end:02d}" in comment
    assert "dini_hari 00-05" in comment
    assert "risk_agent.apply_seasonality" in comment  # skor dasar, pengali saat baca
