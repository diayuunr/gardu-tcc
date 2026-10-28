from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, reports, risk, route
from app.core.config import get_settings
from app.core.safe_log import silence_library_retry_logs

settings = get_settings()

# Log retry internal langchain-google-genai memuat pesan error mentah (bisa
# berisi teks laporan) dan tidak bisa kita ubah — difilter, bukan dibiarkan.
silence_library_retry_logs()

app = FastAPI(
    title="Gardu API",
    description="Backend FastAPI untuk orkestrasi AI Agent Gardu (Verification, Risk Prediction, Safe Route Advisor).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(reports.router)
app.include_router(risk.router)
app.include_router(route.router)
