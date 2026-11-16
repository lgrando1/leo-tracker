import importlib.util
import os
from datetime import datetime
from pathlib import Path
import pytz
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent

# Carrega .env da raiz do workspace e/ou de dentro de v2-htmx/ (ignora silenciosamente se não existir na Vercel)
try:
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(BASE_DIR / ".env")
    load_dotenv()
except Exception:
    pass

TIMEZONE_BR = pytz.timezone("America/Sao_Paulo")


def get_now_br() -> datetime:
    """Retorna o datetime atual no fuso America/Sao_Paulo."""
    return datetime.now(TIMEZONE_BR)


def _clean_env(key: str, default: str = "") -> str:
    val = os.getenv(key, default)
    return val.strip().strip('"').strip("'").strip() if val else default


def _normalize_db_url(url: str) -> str:
    """
    Limpa eventuais aspas extras na DATABASE_URL e ajusta o esquema:
    - Se começar com 'postgres://', converte para 'postgresql+psycopg://' (ou 'postgresql://' se apenas psycopg2 estiver disponível).
    - Se começar com 'postgresql+psycopg://' mas apenas psycopg2 estiver instalado no ambiente, faz fallback automático.
    """
    if not url:
        return ""
    url = url.strip().strip('"').strip("'").strip()

    has_psycopg3 = importlib.util.find_spec("psycopg") is not None
    has_psycopg2 = importlib.util.find_spec("psycopg2") is not None

    if url.startswith("postgres://"):
        if has_psycopg3 or not has_psycopg2:
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        else:
            url = url.replace("postgres://", "postgresql://", 1)
    elif url.startswith("postgresql+psycopg://") and not has_psycopg3 and has_psycopg2:
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif url.startswith("postgresql://") and has_psycopg3 and not has_psycopg2:
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)

    return url


DATABASE_URL: str = _normalize_db_url(_clean_env("DATABASE_URL", ""))

# Credenciais para HTTP Basic Auth
APP_USER: str = _clean_env("APP_USER", "leo") or "leo"
APP_PASSWORD: str = _clean_env("APP_PASSWORD") or _clean_env("PASSWORD") or "admin"

GROQ_API_KEY: str = _clean_env("GROQ_API_KEY", "")
GROQ_MODEL_TEXT: str = _clean_env("GROQ_MODEL_TEXT", "openai/gpt-oss-120b")
GROQ_MODEL_VISION: str = _clean_env("GROQ_MODEL_VISION", "qwen/qwen3.8-27b")

INTERVALS_API_KEY: str = _clean_env("INTERVALS_API_KEY", "")
INTERVALS_ATHLETE_ID: str = _clean_env("INTERVALS_ATHLETE_ID", "")
