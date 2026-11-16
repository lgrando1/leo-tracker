import os
from datetime import datetime
from pathlib import Path
import pytz
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

# Carrega .env da raiz do workspace e/ou de dentro de v2-htmx/
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env")
load_dotenv()

TIMEZONE_BR = pytz.timezone("America/Sao_Paulo")


def get_now_br() -> datetime:
    """Retorna o datetime atual no fuso America/Sao_Paulo."""
    return datetime.now(TIMEZONE_BR)


def _clean_env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val.strip().strip('"').strip("'") if val else default


def _normalize_db_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL: str = _normalize_db_url(_clean_env("DATABASE_URL", ""))

# Suporta APP_PASSWORD ou PASSWORD do .env (com fallback fixo "admin" igual ao @app.py)
APP_PASSWORD: str = _clean_env("APP_PASSWORD") or _clean_env("PASSWORD") or "admin"

# Chave secreta fixa de fallback para evitar invalidação de sessão entre instâncias serverless na Vercel
SECRET_KEY: str = (
    _clean_env("SECRET_KEY")
    or "leotracker-v2-fixed-serverless-secret-key-9f8e7d6c5b4a"
)

GROQ_API_KEY: str = _clean_env("GROQ_API_KEY", "")
GROQ_MODEL_TEXT: str = _clean_env("GROQ_MODEL_TEXT", "openai/gpt-oss-120b")
GROQ_MODEL_VISION: str = _clean_env("GROQ_MODEL_VISION", "qwen/qwen3.8-27b")

INTERVALS_API_KEY: str = _clean_env("INTERVALS_API_KEY", "")
INTERVALS_ATHLETE_ID: str = _clean_env("INTERVALS_ATHLETE_ID", "")
