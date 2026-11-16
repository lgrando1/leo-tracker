from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from app.config import DATABASE_URL

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    """
    Retorna instância singleton do SQLAlchemy Engine configurada com
    pool_pre_ping=True e pool_recycle=300 para evitar problemas de cold start
    ou queda de conexão ociosa no Neon Serverless PostgreSQL.
    """
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError(
                "Variável DATABASE_URL não encontrada no arquivo .env. "
                "Defina DATABASE_URL apontando para o seu banco Neon PostgreSQL."
            )
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=5,
            max_overflow=10,
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
