import os
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool
from app.config import DATABASE_URL, _normalize_db_url

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """
    Retorna instância singleton do SQLAlchemy Engine configurada de forma segura
    para ambientes serverless (Vercel) e local com Neon PostgreSQL.
    """
    global _engine
    if _engine is None:
        db_url = _normalize_db_url(os.getenv("DATABASE_URL", "") or DATABASE_URL)
        if not db_url:
            raise RuntimeError(
                "Variável DATABASE_URL não configurada nas Environment Variables (Vercel / .env)."
            )
        is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
        if is_serverless:
            _engine = create_engine(
                db_url,
                poolclass=NullPool,
                connect_args={"connect_timeout": 10},
            )
        else:
            _engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=5,
                max_overflow=10,
                connect_args={"connect_timeout": 10},
            )
    return _engine


def fetch_all(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Executa SELECT parametrizado e retorna lista de dicionários."""
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        return [dict(row._mapping) for row in result]


def fetch_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Executa SELECT parametrizado e retorna a primeira linha como dicionário ou None."""
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def execute_write(sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    """Executa INSERT/UPDATE/DELETE dentro de uma transação segura."""
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})
