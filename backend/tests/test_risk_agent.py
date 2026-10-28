import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.agents import risk_agent
from app.agents.risk_agent import (
    WIB,
    ScorableIncident,
    compute_risk_scores,
    locate_area,
    lookup_risk_score,
    recalculate_risk_scores,
    refresh_risk_scores_safely,
    seasonal_multiplier,
    time_bucket_of,
)
from app.core.config import get_settings
from app.core.supabase_client import get_supabase
from app.main import app

client = TestClient(app)

# Koordinat & waktu seed "Gedongkuning, Kotagede" (22:00 WIB, 6 April 2022).
GEDONGKUNING = (-7.812995, 110.39872)
GEDONGKUNING_TIME = datetime(2022, 4, 6, 22, 0, tzinfo=WIB)
AS_OF = datetime(2026, 9, 20, 12, 0, tzinfo=WIB)  # bukan musim rawan


def _incident(lat_lon=GEDONGKUNING, when=GEDONGKUNING_TIME) -> ScorableIncident:
    return ScorableIncident(latitude=lat_lon[0], longitude=lat_lon[1], incident_time=when)


# ------------------------------------------------- fake Supabase in-memory


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Emulasi minimal query builder: select/upsert/delete + or_/eq/in_/range/limit."""

    def __init__(self, table, op, payload=None, on_conflict=None):
        self._table, self._op, self._payload, self._on_conflict = table, op, payload, on_conflict
        self._eq, self._in, self._or, self._range, self._limit = [], [], None, None, None

    def or_(self, expression):
        self._table.or_expressions.append(expression)
        self._or = [tuple(part.split(".eq.")) for part in expression.split(",")]
        return self

    def eq(self, key, value):
        self._eq.append((key, value))
        return self

    def in_(self, key, values):
        self._in.append((key, list(values)))
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def limit(self, count):
        self._limit = count
        return self

    @staticmethod
    def _coerce(raw):
        return {"true": True, "false": False}.get(raw, raw)

    def _matches(self, row):
        if any(row.get(k) != v for k, v in self._eq):
            return False
        if any(row.get(k) not in vs for k, vs in self._in):
            return False
        if self._or and not any(row.get(k) == self._coerce(v) for k, v in self._or):
            return False
        return True

    def execute(self):
        rows = self._table.rows
        if self._op == "select":
            matched = [row for row in rows if self._matches(row)]
            if self._range:
                matched = matched[self._range[0] : self._range[1] + 1]
            if self._limit is not None:
                matched = matched[: self._limit]
            return _Resp(matched)
        if self._op == "upsert":
            self._table.upsert_payloads.append(self._payload)
            for item in self._payload:
                existing = next(
                    (r for r in rows if (r["area_name"], r["time_bucket"]) == (item["area_name"], item["time_bucket"])),
                    None,
                )
                if existing:
                    existing.update(item)
                else:
                    rows.append({"id": str(uuid.uuid4()), **item})
            return _Resp(self._payload)
        if self._op == "delete":
            doomed = [row for row in rows if self._matches(row)]
            self._table.deleted_ids.extend(row["id"] for row in doomed)
            self._table.rows[:] = [row for row in rows if row not in doomed]
            return _Resp(doomed)
        raise AssertionError(self._op)


class _Table:
    def __init__(self, rows):
        self.rows = rows
        self.or_expressions: list[str] = []
        self.upsert_payloads: list[list[dict]] = []
        self.deleted_ids: list[str] = []

    def select(self, _columns):
        return _Query(self, "select")

    def upsert(self, payload, on_conflict):
        return _Query(self, "upsert", payload, on_conflict)

    def delete(self):
        return _Query(self, "delete")


class _FakeSupabase:
    def __init__(self, incidents=None, risk_scores=None):
        self.tables = {"incidents": _Table(incidents or []), "risk_scores": _Table(risk_scores or [])}

    def table(self, name):
        return self.tables[name]


def _incident_row(*, is_seed=False, status="baru", lat_lon=GEDONGKUNING, when=GEDONGKUNING_TIME):
    return {
        "id": str(uuid.uuid4()),
        "latitude": lat_lon[0] if lat_lon else None,
        "longitude": lat_lon[1] if lat_lon else None,
        "incident_time": when.isoformat(),
        "is_seed_data": is_seed,
        "status": status,
    }


# ------------------------------------------------ REQ-F-020 / TC-RSK-001, 002


def test_seed_incident_scores_its_area_and_hour_but_not_other_areas_or_hours():
    rows = compute_risk_scores([_incident()], AS_OF, get_settings())

    assert len(rows) == 1
    row = rows[0]
    assert row.time_bucket == "malam"  # 22:00 WIB
    assert row.area_name == "Area -7.815, 110.395"
    # Rumus 10*(1-exp(-0.5^(umur/1825hari))) untuk kejadian 4,45 tahun lalu.
    assert row.risk_score == pytest.approx(4.17, abs=0.05)
    assert row.risk_level == "sedang"
    # Area/jam lain "relatif aman": tidak ada baris -> skor 0 di lookup.
    assert not any(r.time_bucket == "pagi" for r in rows)


def test_more_incidents_in_same_area_and_hour_raise_score_but_never_exceed_ten():
    settings = get_settings()
    one = compute_risk_scores([_incident()], AS_OF, settings)[0].risk_score
    many = compute_risk_scores([_incident() for _ in range(50)], AS_OF, settings)[0]

    assert many.risk_score > one
    assert many.risk_score <= 10.0
    assert many.risk_level == "tinggi"
    assert many.contributing_incident_count == 50


def test_time_bucket_boundaries_use_wib_and_treat_naive_as_wib():
    assert time_bucket_of(datetime(2026, 1, 1, 0, 0, tzinfo=WIB)) == "dini_hari"
    assert time_bucket_of(datetime(2026, 1, 1, 4, 59, tzinfo=WIB)) == "dini_hari"
    assert time_bucket_of(datetime(2026, 1, 1, 5, 0, tzinfo=WIB)) == "pagi"
    assert time_bucket_of(datetime(2026, 1, 1, 23, 59, tzinfo=WIB)) == "malam"
    # 15:00 UTC = 22:00 WIB
    assert time_bucket_of(datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)) == "malam"
    # Tanpa zona waktu = waktu lokal pengguna (WIB)
    assert time_bucket_of(datetime(2026, 1, 1, 2, 30)) == "dini_hari"


# ---------------------------------------------------- REQ-F-023 / TC-RSK-003


def test_seasonal_multiplier_only_applies_before_and_during_ramadan():
    settings = get_settings()  # Ramadan 2027 (1448 H): 8 Feb - 9 Mar 2027

    assert seasonal_multiplier(date(2026, 9, 20), "malam", settings) == 1.0  # di luar musim
    assert seasonal_multiplier(date(2027, 1, 30), "malam", settings) == settings.risk_ramadan_multiplier  # jelang
    assert seasonal_multiplier(date(2027, 1, 24), "malam", settings) == 1.0  # 15 hari sebelum: di luar jendela 14 hari
    assert seasonal_multiplier(date(2027, 2, 20), "malam", settings) == settings.risk_ramadan_multiplier  # selama
    assert seasonal_multiplier(date(2027, 3, 20), "malam", settings) == 1.0  # setelah Ramadan
    # Jam sahur (SOTR) selama Ramadan dapat tambahan; jelang Ramadan tidak.
    assert seasonal_multiplier(date(2027, 2, 20), "dini_hari", settings) == pytest.approx(
        settings.risk_ramadan_multiplier * settings.risk_ramadan_dini_hari_multiplier
    )
    assert seasonal_multiplier(date(2027, 1, 30), "dini_hari", settings) == settings.risk_ramadan_multiplier


def _incident_one_day_before(as_of: datetime) -> ScorableIncident:
    return _incident(when=as_of - timedelta(days=1))


def test_score_is_higher_before_ramadan_than_in_a_normal_period_for_same_incident_age():
    """TC-RSK-003: umur kejadian dibuat identik (1 hari) supaya yang berbeda
    HANYA faktor musim."""
    settings = get_settings()
    normal_as_of = datetime(2026, 9, 20, 12, 0, tzinfo=WIB)
    pre_ramadan_as_of = datetime(2027, 1, 30, 12, 0, tzinfo=WIB)

    normal = compute_risk_scores([_incident_one_day_before(normal_as_of)], normal_as_of, settings)[0].risk_score
    pre_ramadan = compute_risk_scores(
        [_incident_one_day_before(pre_ramadan_as_of)], pre_ramadan_as_of, settings
    )[0].risk_score

    assert pre_ramadan > normal


# ----------------------------------------------- REQ-F-022 + persistensi


def test_only_seed_and_verified_incidents_are_scored_and_stale_rows_are_removed():
    cell = get_settings().risk_grid_cell_degrees
    unverified_position = (-7.70, 110.30)
    seed = _incident_row(is_seed=True)
    verified = _incident_row(status="terverifikasi", lat_lon=(-7.7956, 110.3695))
    unverified = _incident_row(status="baru", lat_lon=unverified_position)  # solo, belum ada korroborasi
    no_coordinates = _incident_row(is_seed=True, lat_lon=None)
    stale_score = {"id": "usang-1", "area_name": "Area -1.000, 1.000", "time_bucket": "pagi"}
    fake = _FakeSupabase(
        incidents=[seed, verified, unverified, no_coordinates], risk_scores=[stale_score]
    )

    result = recalculate_risk_scores(AS_OF, supabase=fake)

    assert fake.tables["incidents"].or_expressions == ["is_seed_data.eq.true,status.eq.terverifikasi"]
    assert result.incidents_used == 2  # seed + terverifikasi; 'baru' tidak ikut (REQ-F-022)
    assert result.incidents_skipped_without_coordinates == 1
    saved_areas = {row["area_name"] for row in fake.tables["risk_scores"].rows}
    assert locate_area(*unverified_position, cell)[2] not in saved_areas  # insiden 'baru' tidak jadi skor
    assert "Area -1.000, 1.000" not in saved_areas  # baris usang dihapus
    assert fake.tables["risk_scores"].deleted_ids == ["usang-1"]
    assert result.upserted == 2


def test_recalculation_is_idempotent_and_never_stores_incident_text_or_exact_coordinates():
    fake = _FakeSupabase(incidents=[_incident_row(is_seed=True)])

    first = recalculate_risk_scores(AS_OF, supabase=fake)
    second = recalculate_risk_scores(AS_OF, supabase=fake)

    assert len(fake.tables["risk_scores"].rows) == first.upserted == second.upserted == 1
    stored = fake.tables["risk_scores"].rows[0]
    # REQ-F-042/REQ-NF-120: koordinat = pusat sel grid, bukan titik insiden asli.
    assert (stored["latitude"], stored["longitude"]) == (-7.815, 110.395)
    assert (stored["latitude"], stored["longitude"]) != GEDONGKUNING
    assert set(stored) <= {
        "id", "area_name", "latitude", "longitude", "time_bucket", "risk_score",
        "risk_level", "contributing_incident_count", "last_calculated_at",
    }


# ----------------------------------------------------- pemicu (fig4 langkah 5-6)


@pytest.fixture
def clean_trigger_state(monkeypatch):
    monkeypatch.setattr(risk_agent, "_recalculation_running", False)
    monkeypatch.setattr(risk_agent, "_rerun_requested", False)


def test_concurrent_triggers_are_coalesced_into_one_extra_run(monkeypatch, clean_trigger_state):
    calls: list[int] = []

    def slow_recalculation():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            # Tiga pemicu baru datang SAAT perhitungan pertama masih berjalan.
            refresh_risk_scores_safely()
            refresh_risk_scores_safely()
            refresh_risk_scores_safely()
        return risk_agent.RecalculationResult()

    monkeypatch.setattr(risk_agent, "recalculate_risk_scores", slow_recalculation)

    refresh_risk_scores_safely()
    assert calls == [1, 2]  # 1 perhitungan awal + tepat 1 putaran ulang, bukan 4

    refresh_risk_scores_safely()  # setelah selesai, pemicu berikutnya jalan normal lagi
    assert calls == [1, 2, 3]


def test_failed_recalculation_never_raises_and_log_has_no_raw_message(monkeypatch, caplog, clean_trigger_state):
    def broken():
        raise RuntimeError("gagal memproses RAHASIA-LAPORAN nomor hp 081234567890")

    monkeypatch.setattr(risk_agent, "recalculate_risk_scores", broken)

    with caplog.at_level(logging.DEBUG, logger="app.agents.risk_agent"):
        refresh_risk_scores_safely()  # tidak boleh raise ke Verification Agent

    assert "RAHASIA-LAPORAN" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    assert any("GAGAL" in record.getMessage() and "RuntimeError" in record.getMessage() for record in caplog.records)
    assert risk_agent._recalculation_running is False  # state pulih, pemicu berikutnya bisa jalan


# ------------------------------------------------------------ endpoint lookup


def _override_supabase(fake):
    app.dependency_overrides[get_supabase] = lambda: fake


def _stored_score_row(**overrides):
    area_name = locate_area(*GEDONGKUNING, get_settings().risk_grid_cell_degrees)[2]
    row = {
        "id": "s-1", "area_name": area_name, "time_bucket": "malam",
        "risk_score": 4.17, "risk_level": "sedang", "contributing_incident_count": 1,
    }
    row.update(overrides)
    return row


def test_score_endpoint_returns_stored_score_for_the_area_and_time():
    _override_supabase(_FakeSupabase(risk_scores=[_stored_score_row()]))
    try:
        response = client.get(
            "/risk/score", params={"lat": GEDONGKUNING[0], "lon": GEDONGKUNING[1], "at": "2026-09-20T22:30:00"}
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 200
    assert response.json() == {
        "area_name": "Area -7.815, 110.395", "time_bucket": "malam", "risk_score": 4.17,
        "risk_level": "sedang", "contributing_incident_count": 1, "has_data": True,
        "narrative": None,  # default include_narrative=false -> jalur cepat, tanpa Gemini
    }


def test_score_endpoint_reports_no_data_instead_of_claiming_safe_for_unknown_area_or_hour():
    _override_supabase(_FakeSupabase(risk_scores=[_stored_score_row()]))
    try:
        other_hour = client.get(
            "/risk/score", params={"lat": GEDONGKUNING[0], "lon": GEDONGKUNING[1], "at": "2026-09-20T09:00:00"}
        )
        other_area = client.get("/risk/score", params={"lat": -7.5, "lon": 110.1, "at": "2026-09-20T22:30:00"})
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    for response in (other_hour, other_area):
        body = response.json()
        assert response.status_code == 200
        assert (body["risk_score"], body["risk_level"], body["has_data"]) == (0.0, "rendah", False)


def test_score_endpoint_validates_input_at_the_api_level():
    assert client.get("/risk/score", params={"lat": 95, "lon": 110}).status_code == 422
    assert client.get("/risk/score", params={"lat": -7.8, "lon": 200}).status_code == 422
    assert client.get("/risk/score", params={"lat": -7.8}).status_code == 422
    assert client.get("/risk/score", params={"lat": -7.8, "lon": 110, "at": "bukan-tanggal"}).status_code == 422


def test_score_endpoint_returns_502_and_never_leaks_database_details(caplog):
    class _BrokenSupabase:
        def table(self, _name):
            raise RuntimeError("RAHASIA-DB-DETAIL nomor hp 081234567890")

    _override_supabase(_BrokenSupabase())
    try:
        with caplog.at_level(logging.DEBUG):
            response = client.get("/risk/score", params={"lat": -7.8, "lon": 110.3})
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 502
    assert "RAHASIA-DB-DETAIL" not in response.text
    assert "RAHASIA-DB-DETAIL" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_lookup_and_computation_use_the_same_area_key_for_the_same_point():
    """Kunci area harus identik antara perhitungan dan lookup, kalau tidak
    skor tersimpan tidak pernah ketemu."""
    settings = get_settings()
    computed_name = compute_risk_scores([_incident()], AS_OF, settings)[0].area_name
    fake = _FakeSupabase(risk_scores=[_stored_score_row(area_name=computed_name)])

    result = lookup_risk_score(fake, GEDONGKUNING[0] + 0.001, GEDONGKUNING[1] - 0.001, GEDONGKUNING_TIME)

    assert result.has_data is True  # titik berbeda ~100 m tapi masih satu sel grid
    assert result.area_name == computed_name
