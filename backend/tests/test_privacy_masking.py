"""Tes penyamaran data pribadi di deskripsi laporan (REQ-NF-120): masking, bukan penolakan."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.api.reports as reports_module
from app.agents import verify_agent
from app.core.privacy import EMAIL_MASK, NUMBER_MASK, mask_personal_data
from app.core.supabase_client import get_supabase
from app.main import app
from app.schemas.report import ReportCreate

client = TestClient(app)
NOW_MINUS_1H = lambda: datetime.now(timezone.utc) - timedelta(hours=1)  # noqa: E731


@pytest.mark.parametrize(
    "phone",
    [
        "081234567890", "0812-3456-7890", "0812 3456 7890", "0812.3456.7890",
        "+6281234567890", "+62 812 3456 7890", "+62-812-3456-7890", "6281234567890", "62812-3456-7890",
        "0274-512345", "0274 512345", "(0274) 512345", "0274512345",
    ],
)
def test_indonesian_phone_numbers_are_masked_in_all_common_formats(phone):
    masked = mask_personal_data(f"korban minta dihubungi di {phone} segera")

    assert masked == f"korban minta dihubungi di {NUMBER_MASK} segera"
    assert "812" not in masked and "512345" not in masked


def test_emails_are_masked():
    assert mask_personal_data("kontak budi.santoso+gardu@mail.contoh.co.id ya") == f"kontak {EMAIL_MASK} ya"
    assert mask_personal_data("a@b.co dan c@d.org") == f"{EMAIL_MASK} dan {EMAIL_MASK}"


@pytest.mark.parametrize("nik", ["3404123456789012", "3404 1234 5678 9012", "3404-1234-5678-9012", "6271234567890123"])
def test_16_digit_nik_is_masked_including_province_code_62_that_looks_like_a_phone_prefix(nik):
    assert mask_personal_data(f"NIK pelaku {nik} terbaca") == f"NIK pelaku {NUMBER_MASK} terbaca"


@pytest.mark.parametrize(
    "text",
    [
        "motor AB 1234 CD dihadang dua orang",
        "plat B 1234 XYZ kabur ke utara",
        "plat AB1234CD",
        "DK 5678 AA dan AA 9012 BC",
        "plat N 1 A",
        "plat AB 0812 CD",  # digit berawalan 0 di dalam plat
        "kejadian jam 02.30 sampai 03.15 lalu 04.00",
        "tanggal 28-10-2026 pukul 23.30",
        "dirampas Rp 50.000 dan Rp 62.000.000",
        "sekitar 20 orang naik 3 motor di km 5",
    ],
)
def test_vehicle_plates_times_dates_and_amounts_are_not_masked(text):
    assert mask_personal_data(text) == text  # nomor polisi = informasi kejadian yang sah


def test_masking_is_selective_idempotent_and_leaves_the_rest_intact():
    text = "Motor AB 1234 CD dihadang di Jl. Kaliurang km 5, hubungi 0812-3456-7890 / saya@mail.com, NIK 3404123456789012."

    once = mask_personal_data(text)

    assert once == (
        f"Motor AB 1234 CD dihadang di Jl. Kaliurang km 5, hubungi {NUMBER_MASK} / {EMAIL_MASK}, NIK {NUMBER_MASK}."
    )
    assert mask_personal_data(once) == once


# ----------------------------------------------------------------------------- skema & endpoint


def test_report_schema_masks_description_and_legacy_location_text_instead_of_rejecting():
    report = ReportCreate(
        description="Ada begal di Kaliurang plat AB 1234 CD, telp saksi 081234567890 atau saksi@mail.com",
        location_text="Warung dekat rumah, hubungi 0812-3456-7890",
        occurred_at=NOW_MINUS_1H(),
    )

    assert report.description == f"Ada begal di Kaliurang plat AB 1234 CD, telp saksi {NUMBER_MASK} atau {EMAIL_MASK}"
    assert report.location_text == f"Warung dekat rumah, hubungi {NUMBER_MASK}"


def test_description_that_is_mostly_personal_data_is_still_accepted():
    report = ReportCreate(description="081234567890 saksi 3404123456789012", location_text="Kaliurang", occurred_at=NOW_MINUS_1H())

    assert NUMBER_MASK in report.description and "0812" not in report.description


def test_endpoint_stores_the_masked_text_and_never_echoes_it(monkeypatch):
    saved: list[dict] = []

    class _Table:
        def insert(self, record):
            saved.append(record)
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": "r-1", "status": "menunggu_verifikasi", "created_at": "2026-09-20T00:00:00+00:00"}])

    monkeypatch.setattr(reports_module, "process_report_verification", lambda _id: None)
    app.dependency_overrides[get_supabase] = lambda: SimpleNamespace(table=lambda _n: _Table())
    try:
        response = client.post(
            "/reports",
            json={
                "description": "Dihadang di Ring Road plat AB 1234 CD. Hubungi saya 0812-3456-7890 / budi@mail.com NIK 3404123456789012",
                "location_text": "Ring Road Utara",
                "occurred_at": NOW_MINUS_1H().isoformat(),
            },
        )
    finally:
        app.dependency_overrides.pop(get_supabase, None)

    assert response.status_code == 201  # tidak ditolak
    stored = saved[0]["description"]
    assert stored == f"Dihadang di Ring Road plat AB 1234 CD. Hubungi saya {NUMBER_MASK} / {EMAIL_MASK} NIK {NUMBER_MASK}"
    assert "0812" not in response.text and "budi" not in response.text


# ------------------------------------------------- verifikasi: data lama juga tidak sampai ke Gemini


class _Db:
    def __init__(self, report):
        self.report = report
        self.tables = {"reports": [report], "incidents": []}

    def table(self, name):
        return _Table(self.tables[name])

    def rpc(self, *_a, **_k):
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))


class _Table:
    def __init__(self, rows):
        self.rows = rows
        self._filters: list[tuple] = []
        self._op = "select"
        self._payload = None

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        matched = [r for r in self.rows if all(r.get(k) == v for k, v in self._filters)]
        if self._op == "update":
            for row in matched:
                row.update(self._payload)
        elif self._op == "insert":
            matched = [{"id": str(uuid.uuid4()), **self._payload}]
            self.rows.extend(matched)
        return SimpleNamespace(data=matched, count=len(matched))


def test_legacy_unmasked_rows_are_masked_before_reaching_gemini_extraction_and_embedding(monkeypatch):
    report = {
        "id": str(uuid.uuid4()),
        "description": "Dihadang plat AB 1234 CD, saksi bisa dihubungi 0812-3456-7890 atau saksi@mail.com",
        "location_text": "Kaliurang", "latitude": -7.75, "longitude": 110.37, "coordinate_source": "client", "jalan": None,
        "occurred_at": datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc).isoformat(),
        "incident_id": None, "status": "menunggu_verifikasi", "extracted_incident_type": None,
    }
    seen = {"extract": [], "embed": []}
    monkeypatch.setattr(verify_agent, "get_supabase", lambda: _Db(report))
    monkeypatch.setattr(verify_agent, "extract_incident_type", lambda text: seen["extract"].append(text) or "penyerangan")
    monkeypatch.setattr(verify_agent, "generate_embedding", lambda text: seen["embed"].append(text) or [0.1] * 768)
    monkeypatch.setattr(verify_agent, "refresh_risk_scores_safely", lambda: None)

    verify_agent.process_report_verification(report["id"])

    expected = f"Dihadang plat AB 1234 CD, saksi bisa dihubungi {NUMBER_MASK} atau {EMAIL_MASK}"
    assert seen["extract"] == [expected] and seen["embed"] == [expected]
    assert report["embedding"] == [0.1] * 768  # verifikasi tetap berjalan normal
