"""FastAPI app untuk Gardu backend."""

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, field_validator, model_validator
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.risk_prediction import RiskAgentError, UnknownAreaError, calculate_risk_score
from backend.agents.route_advisor import RouteAdvisorError, check_route
from backend.agents.verification import VerificationError, verify_report
from backend.db.queries import (
    DBQueryError,
    get_area_names,
    get_report_by_id,
    insert_report,
    update_report_verification,
    upsert_risk_score,
)

WIB = timezone(timedelta(hours=7))
VALID_TIME_SLOTS = ("dini_hari", "pagi", "siang", "sore", "malam")

# Asal frontend yang boleh memanggil API ini. Atur lewat variabel CORS_ORIGINS
# (pisahkan dengan koma), mis. di Render:
#   CORS_ORIGINS=https://gardu-tcc.vercel.app,http://localhost:3000
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "http://localhost:3000","https://gardu-tcc.vercel.app").split(",")
    if origin.strip()
]

app = FastAPI(title="Gardu Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_RE_KABKOTA = re.compile(r"^\d{2}\.\d{2}$")
_RE_KECAMATAN = re.compile(r"^\d{2}\.\d{2}\.\d{2}$")
_RE_KELURAHAN = re.compile(r"^\d{2}\.\d{2}\.\d{2}\.\d{4}$")


class ReportCreate(BaseModel):
    description: str
    reported_at: datetime
    # Jalur baru: alamat berjenjang (kode dari tabel areas)
    kabkota_kode: Optional[str] = None
    kecamatan_kode: Optional[str] = None
    kelurahan_kode: Optional[str] = None
    jalan: Optional[str] = None
    # Jalur lama (tetap diterima): teks lokasi bebas
    location: Optional[str] = None

    @field_validator("description")
    @classmethod
    def description_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("tidak boleh kosong")
        return value

    @field_validator("jalan")
    @classmethod
    def jalan_valid(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 200:
            raise ValueError("maksimal 200 karakter")
        return value or None

    @model_validator(mode="after")
    def check_alamat(self):
        # string kosong dianggap tidak diisi
        self.kabkota_kode = self.kabkota_kode or None
        self.kecamatan_kode = self.kecamatan_kode or None
        self.kelurahan_kode = self.kelurahan_kode or None
        self.location = (self.location or "").strip() or None

        if self.kabkota_kode and not _RE_KABKOTA.match(self.kabkota_kode):
            raise ValueError("kabkota_kode tidak valid (contoh: 34.04)")
        if self.kecamatan_kode and not _RE_KECAMATAN.match(self.kecamatan_kode):
            raise ValueError("kecamatan_kode tidak valid (contoh: 34.04.02)")
        if self.kelurahan_kode and not _RE_KELURAHAN.match(self.kelurahan_kode):
            raise ValueError("kelurahan_kode tidak valid (contoh: 34.04.02.2001)")
        if self.kelurahan_kode and not self.kecamatan_kode:
            raise ValueError("kelurahan_kode butuh kecamatan_kode")
        if self.kecamatan_kode and not self.kabkota_kode:
            raise ValueError("kecamatan_kode butuh kabkota_kode")

        punya_kode = bool(self.kabkota_kode and self.kecamatan_kode)
        if not punya_kode and not self.location:
            raise ValueError("isi kabkota_kode + kecamatan_kode, atau location")
        return self

class ReportCreateResponse(BaseModel):
    id: UUID
    status: str

class VerifyRequest(BaseModel):
    report_id: UUID
    text: str


class RouteCheckRequest(BaseModel):
    origin: str
    destination: str
    departure_time: str
    # Opsional: kode wilayah (areas.kode) untuk tiap ujung. Kalau diisi, dipakai
    # menggantikan pencocokan nama.
    origin_kode: Optional[str] = None
    destination_kode: Optional[str] = None


@app.get("/agents/risk")
def get_risk(area: str, time_slot: str):
    """Sesuai docs/contracts.md — Risk Prediction Agent.

    Response: { "area": string, "time_slot": string, "score": number }

    time_slot harus salah satu dari 5 kategori, dan area harus ada di tabel areas
    (tingkat kab/kota atau kecamatan). Kalau tidak, ditolak dan TIDAK ada yang
    ditulis ke risk_scores.
    """
    if time_slot not in VALID_TIME_SLOTS:
        raise HTTPException(
            status_code=422,
            detail=f"time_slot harus salah satu dari: {', '.join(VALID_TIME_SLOTS)}",
        )
    try:
        result = calculate_risk_score(area, time_slot)
        upsert_risk_score(result["area"], result["time_slot"], result["score"])
    except UnknownAreaError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RiskAgentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result


@app.post("/agents/route-check")
def route_check_endpoint(payload: RouteCheckRequest):
    """Sesuai docs/contracts.md — Safe Route Advisor."""
    try:
        return check_route(
            payload.origin,
            payload.destination,
            payload.departure_time,
            origin_kode=payload.origin_kode,
            destination_kode=payload.destination_kode,
        )
    except RouteAdvisorError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/reports", response_model=ReportCreateResponse, status_code=status.HTTP_201_CREATED)
def create_report(payload: ReportCreate):
    """Terima laporan warga. Status awal selalu "menunggu_verifikasi"
    (embedding diisi belakangan oleh Verification Agent, bukan di sini).

    Dua jalur: alamat berjenjang (kabkota_kode + kecamatan_kode [+ kelurahan_kode] [+ jalan])
    atau jalur lama (hanya location). Di jalur baru, location disusun di sini."""
    # Waktu tanpa zona dianggap WIB. Tanpa ini, database membacanya sebagai UTC
    # dan jam laporan bergeser 7 jam.
    reported_at = payload.reported_at
    if reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=WIB)

    location = payload.location
    if payload.kabkota_kode and payload.kecamatan_kode:
        kodes = [payload.kabkota_kode, payload.kecamatan_kode, payload.kelurahan_kode]
        try:
            nama = get_area_names(kodes)
        except DBQueryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        tidak_dikenal = [k for k in kodes if k and k not in nama]
        if tidak_dikenal:
            raise HTTPException(
                status_code=422,
                detail=f"Kode wilayah tidak dikenal: {', '.join(tidak_dikenal)}",
            )

        # location disusun dari pilihan wilayah (nama dari tabel areas), bukan dari klien
        bagian = [
            payload.jalan,
            nama.get(payload.kelurahan_kode),
            nama.get(payload.kecamatan_kode),
            nama.get(payload.kabkota_kode),
        ]
        location = ", ".join(b for b in bagian if b)

    try:
        row = insert_report(
            {
                "description": payload.description,
                "location": location,
                "reported_at": reported_at.isoformat(),
                "status": "menunggu_verifikasi",
                "kabkota_kode": payload.kabkota_kode,
                "kecamatan_kode": payload.kecamatan_kode,
                "kelurahan_kode": payload.kelurahan_kode,
                "jalan": payload.jalan,
            }
        )
    except DBQueryError as exc:
        pesan = str(exc)
        # 23503 = foreign key, 23514 = check constraint: kombinasi wilayah tidak konsisten
        if "23503" in pesan or "23514" in pesan:
            raise HTTPException(
                status_code=422,
                detail="Kombinasi wilayah tidak valid: kelurahan harus milik kecamatan itu, "
                "dan kecamatan harus milik kab/kota itu.",
            ) from exc
        raise HTTPException(status_code=500, detail=pesan) from exc

    return {"id": row["id"], "status": row["status"]}


@app.get("/reports/{report_id}")
def get_report(report_id: UUID):
    """Ambil satu laporan berdasarkan id — untuk testing/verifikasi manual."""
    try:
        row = get_report_by_id(str(report_id))
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if row is None:
        raise HTTPException(status_code=404, detail="Report tidak ditemukan")

    return row


@app.post("/agents/verify")
def verify_report_endpoint(payload: VerifyRequest):
    """Sesuai docs/contracts.md — Verification Agent. 503 kalau API AI
    gagal/timeout — jangan biarkan request menggantung."""
    report_id = str(payload.report_id)

    # Cek laporannya dulu: id yang tidak ada ditolak SEBELUM Gemini dipanggil (hemat kuota).
    try:
        report = get_report_by_id(report_id)
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if report is None:
        raise HTTPException(status_code=404, detail="Report tidak ditemukan")

    try:
        result = verify_report(report_id, payload.text, report=report)
    except VerificationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    new_status = "terverifikasi" if result["cluster_id"] else "menunggu_verifikasi"
    try:
        # location SENGAJA tidak dikirim: alamat dari form tidak boleh ditimpa tebakan Gemini
        update_report_verification(report_id, status=new_status)
    except DBQueryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return result
