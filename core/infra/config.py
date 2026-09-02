"""Configuration for the intentionally small public showcase."""

import os
from pathlib import Path


APP_NAME = "Najemnik"
APP_VERSION = os.environ.get("APP_VERSION", "portfolio-demo-1")
DEMO_MODE = True

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
PHOTOS_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "demo.db"
DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DB_PATH.as_posix()}")

LOGO_LIGHT = "/static/img/logo-light.png"
LOGO_DARK = "/static/img/logo-dark.png"

# The hosted application never calls a model. These values remain because
# core/pipeline/enrich is a selected, inspectable sample of the real local-LLM
# architecture used by the private project.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "SpeakLeash/bielik-11b-v3.0-instruct:Q5_K_M")
OLLAMA_TIMEOUT = 180
OLLAMA_FIELD_TIMEOUT = 120
QUOTA_ENRICH_PER_DAY = 100

# The cookie signs an opaque random token whose hash is stored in SQLite.
# A deployment may override this; no private production secret is required.
SECRET_KEY = os.environ.get("SECRET_KEY", "public-showcase-cookie-signing-key")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
SESSION_COOKIE_NAME = "najemnik_session"
SESSION_TTL_DAYS = 1

ASSUMED_UTILITY_COSTS = {
    "woda": 0,
    "ogrzewanie": 0,
    "smieci": 0,
    "prad": 150,
    "gaz": 100,
    "internet": 50,
}
ASSUMED_HEATING_COST_BY_TYPE = {
    "gazowe": 250,
    "elektryczne": 300,
    "kominkowe": 100,
    "inne": 150,
}

HTTP_HEADERS = {
    "User-Agent": "Najemnik portfolio source sample",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
