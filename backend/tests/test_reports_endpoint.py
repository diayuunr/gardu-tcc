"""Test endpoint Report Submission (POST /reports, GET /reports/{id})."""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "description": "Ada gerombolan remaja bawa celurit di pinggir jalan",
    "location": "Jalan Test Otomatis, Bantul",
    "reported_at": "2026-09-20T02:00:00+07:00",
}


def test_create_report_valid_returns_201():
    response = client.post("/reports", json=VALID_PAYLOAD)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "menunggu_verifikasi"
    assert "id" in body


def test_create_report_blank_description_returns_422():
    payload = {**VALID_PAYLOAD, "description": "   "}
    response = client.post("/reports", json=payload)
    assert response.status_code == 422


def test_get_report_found_returns_200():
    created = client.post("/reports", json=VALID_PAYLOAD).json()

    response = client.get(f"/reports/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_report_not_found_returns_404():
    random_id = uuid4()
    response = client.get(f"/reports/{random_id}")
    assert response.status_code == 404
