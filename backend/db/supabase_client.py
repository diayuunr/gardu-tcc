"""Supabase client singleton untuk backend Gardu.

Dipakai oleh modul lain lewat: from backend.db.supabase_client import supabase
"""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

_missing = [
    name
    for name, value in [
        ("SUPABASE_URL", SUPABASE_URL),
        ("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_SERVICE_ROLE_KEY),
    ]
    if not value
]
if _missing:
    raise RuntimeError(
        "Env variable belum di-set: "
        + ", ".join(_missing)
        + ". Copy .env.example ke .env lalu isi nilainya sebelum menjalankan backend."
    )

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
