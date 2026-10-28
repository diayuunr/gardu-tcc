from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import areas, geo, health, internal, moderation, reports, reports_public, risk, route
from app.core.config import get_settings
from app.core.cors import parse_cors_origins
from app.core.errors import install_error_handling
from app.core.safe_log import harden_logging, silence_library_retry_logs
from app.core.warmup import start_warmup_thread

settings = get_settings()

# Log retry internal langchain-google-genai memuat pesan error mentah (bisa
# berisi teks laporan) dan tidak bisa kita ubah — difilter, bukan dibiarkan.
silence_library_retry_logs()
harden_logging()  # log akses tanpa IP/query string; httpx tidak mencatat URL (token & kata kunci)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.startup_warmup_enabled:
        start_warmup_thread()
    yield


app = FastAPI(
    title="Gardu API",
    description="Backend FastAPI untuk orkestrasi AI Agent Gardu (Verification, Risk Prediction, Safe Route Advisor).",
    version="0.1.0",
    lifespan=lifespan,
)

# Urutan penting: yang dipasang TERAKHIR berada paling luar. Penanganan error dipasang dulu
# (di dalam), CORS sesudahnya (di luar) supaya respons error pun membawa header CORS.
install_error_handling(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(settings.cors_allow_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(areas.router)
app.include_router(geo.router)
app.include_router(reports.router)
app.include_router(reports_public.router)
app.include_router(moderation.router)
app.include_router(internal.router)
app.include_router(risk.router)
app.include_router(route.router)
