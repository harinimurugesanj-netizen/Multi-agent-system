"""Database engine and the single transaction helper used by every DB-touching node."""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from config.config import get_settings
from app.errors import AppError, DatabaseUnavailable, PersistenceError
from config.logging_config import get_logger

log = get_logger(__name__)


def to_sqlalchemy_url(url: str) -> str:
    """SQLAlchemy needs the driver name; psycopg (v3) is used everywhere in this project."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache
def get_engine() -> Engine:
    # pool_pre_ping drops dead connections instead of failing the next request.
    return create_engine(to_sqlalchemy_url(get_settings().database_url),
                         pool_pre_ping=True, pool_size=5, max_overflow=5)


@contextmanager
def db_transaction(engine: Engine | None = None) -> Iterator[Connection]:
    """Commit on success, roll back on any error, and translate DB errors into AppErrors."""
    try:
        with (engine or get_engine()).begin() as conn:
            yield conn
    except AppError:
        raise
    except (OperationalError, InterfaceError) as exc:
        log.error("db_unavailable", error=str(exc)[:200])
        raise DatabaseUnavailable(str(exc)[:200]) from exc
    except SQLAlchemyError as exc:
        log.error("db_error", error=str(exc)[:200])
        raise PersistenceError(str(exc)[:200]) from exc
