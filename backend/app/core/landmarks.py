"""Landmark DIY kurasi lokal (backend/data/landmarks.json) — lapisan pertama pencarian tempat.

Cakupan POI Mapbox/OSM untuk landmark Indonesia sering lemah ("Universitas Gadjah Mada" 0 hasil, "Tugu
Yogyakarta" salah cocok ke desa di Klaten), jadi tempat populer ditulis manual: nama, alias (singkatan,
ejaan lain), kategori, dan koordinat. KOORDINAT TIDAK BOLEH ASAL: `validate_landmarks` menolak entri di luar
DIY, nama/alias ganda, kategori/keyakinan tak dikenal; kolom `keyakinan` menandai koordinat yang masih perlu
ditinjau manusia.

Pencocokan memakai normalisasi (huruf kecil, tanpa aksen/tanda baca, ejaan varian "jogja"→"yogyakarta",
"jl"→"jalan", "kraton"→"keraton", dst.), lalu berjenjang: sama persis > awalan > setiap kata query adalah awalan
kata di nama/alias (cocok untuk autocomplete "univ gadjah") > mengandung > fuzzy ringan untuk salah ketik.
"""

import difflib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.areas import in_diy

logger = logging.getLogger(__name__)

LANDMARKS_PATH = Path(__file__).resolve().parents[2] / "data" / "landmarks.json"
CATEGORIES = frozenset(
    {"monumen", "kampus", "transportasi", "wisata", "pantai", "belanja", "pasar", "kesehatan", "religi",
     "olahraga", "pemerintahan", "kawasan", "sekolah", "kuliner"}
)
CONFIDENCE_LEVELS = frozenset({"tinggi", "sedang", "perlu_tinjau"})

# Ejaan varian yang disatukan (dipakai pada query DAN nama/alias, jadi konsisten dua arah).
_SPELLING = {
    "jogja": "yogyakarta", "jogjakarta": "yogyakarta", "yogya": "yogyakarta", "jogya": "yogyakarta",
    "jl": "jalan", "kraton": "keraton", "gede": "gedhe", "ambarukmo": "ambarrukmo", "adisucipto": "adisutjipto",
    "bringharjo": "beringharjo",
}


class LandmarkDataError(ValueError):
    """landmarks.json tidak valid; pesan menjelaskan semua masalah."""


def normalize(text: str) -> str:
    """Huruf kecil, tanpa aksen/tanda baca, spasi dirapikan, ejaan varian disatukan."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    tokens = re.sub(r"[^a-z0-9]+", " ", stripped.casefold()).split()
    return " ".join(_SPELLING.get(token, token) for token in tokens)


@dataclass(frozen=True)
class Landmark:
    nama: str
    alias: tuple[str, ...]
    kategori: str
    latitude: float
    longitude: float
    keyakinan: str

    @property
    def names(self) -> tuple[str, ...]:
        return (self.nama, *self.alias)


def validate_landmarks(raw: object) -> tuple[Landmark, ...]:
    """Validasi isi landmarks.json. Melempar LandmarkDataError berisi SEMUA masalah (bukan hanya yang pertama)."""
    problems: list[str] = []
    entries = raw.get("tempat") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        raise LandmarkDataError("landmarks.json harus berisi objek dengan daftar 'tempat' yang tidak kosong")

    landmarks: list[Landmark] = []
    owner: dict[str, str] = {}  # nama/alias ternormalisasi -> nama landmark pemiliknya
    for position, entry in enumerate(entries, start=1):
        where = f"entri #{position}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: bukan objek")
            continue
        nama = entry.get("nama")
        if not isinstance(nama, str) or not nama.strip():
            problems.append(f"{where}: 'nama' kosong")
            continue
        where = f"'{nama}'"
        alias = entry.get("alias", [])
        if not isinstance(alias, list) or not all(isinstance(a, str) and a.strip() for a in alias):
            problems.append(f"{where}: 'alias' harus daftar teks tak kosong")
            alias = []
        if entry.get("kategori") not in CATEGORIES:
            problems.append(f"{where}: kategori '{entry.get('kategori')}' tidak dikenal")
        if entry.get("keyakinan") not in CONFIDENCE_LEVELS:
            problems.append(f"{where}: keyakinan '{entry.get('keyakinan')}' tidak dikenal")
        lat, lon = entry.get("lat"), entry.get("lon")
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
            problems.append(f"{where}: lat/lon harus angka")
            continue
        if not in_diy(lat, lon):
            problems.append(f"{where}: koordinat ({lat}, {lon}) di luar DIY")
        for text in (nama, *alias):
            key = normalize(text)
            if not key:
                problems.append(f"{where}: nama/alias '{text}' kosong setelah normalisasi")
            elif key in owner and owner[key] != nama:
                problems.append(f"{where}: '{text}' bentrok dengan '{owner[key]}' (nama/alias ganda)")
            else:
                owner[key] = nama
        landmarks.append(
            Landmark(nama.strip(), tuple(a.strip() for a in alias), entry.get("kategori", ""), float(lat), float(lon),
                     entry.get("keyakinan", ""))
        )
    names = [normalize(l.nama) for l in landmarks]
    problems.extend(f"nama ganda: '{n}'" for n in sorted({n for n in names if names.count(n) > 1}))
    if problems:
        raise LandmarkDataError("; ".join(problems))
    return tuple(landmarks)


def load_landmarks(path: Path | None = None) -> tuple[Landmark, ...]:
    with open(path or LANDMARKS_PATH, encoding="utf-8") as handle:
        return validate_landmarks(json.load(handle))


@lru_cache(maxsize=1)
def get_landmarks() -> tuple[Landmark, ...]:
    """Landmark dari berkas bawaan. Berkas hilang/rusak TIDAK menjatuhkan server: pencarian jatuh ke lapisan lain."""
    try:
        return load_landmarks()
    except (OSError, ValueError) as exc:  # json.JSONDecodeError adalah ValueError
        logger.error("landmarks.json tidak dapat dimuat, lapisan landmark dimatikan: %s", type(exc).__name__)
        return ()


# ------------------------------------------------------------------ pencocokan


def _score(query: str, query_tokens: list[str], candidate: str) -> float:
    """Skor 0-100 kecocokan satu nama/alias ternormalisasi; 0 = tidak cocok."""
    if query == candidate:
        return 100.0
    candidate_tokens = candidate.split()
    if len(query) >= 3 and candidate.startswith(query):
        return 90.0
    if len(query) >= 3 and all(any(t.startswith(q) for t in candidate_tokens) for q in query_tokens):
        return 80.0
    if len(query) >= 4 and query in candidate:
        return 70.0
    if len(query) >= 4:  # salah ketik ringan, termasuk autocomplete yang belum selesai
        ratio = max(
            difflib.SequenceMatcher(None, query, candidate).ratio(),
            difflib.SequenceMatcher(None, query, candidate[: len(query) + 2]).ratio() - 0.05,
        )
        if ratio >= 0.82:
            return 50.0 + ratio * 10
    return 0.0


def match_landmarks(query: str, limit: int = 5, landmarks: tuple[Landmark, ...] | None = None) -> list[Landmark]:
    """Landmark yang cocok dengan `query`, terbaik dulu (skor ↓, lalu nama pendek, lalu alfabet)."""
    normalized = normalize(query)
    if len(normalized) < 2:
        return []
    tokens = normalized.split()
    scored: list[tuple[float, Landmark]] = []
    for landmark in landmarks if landmarks is not None else get_landmarks():
        best = max(_score(normalized, tokens, normalize(name)) for name in landmark.names)
        if best >= 50:
            scored.append((best, landmark))
    scored.sort(key=lambda item: (-item[0], len(item[1].nama), item[1].nama))
    return [landmark for _, landmark in scored[:limit]]
