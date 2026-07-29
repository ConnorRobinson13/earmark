"""Database wiring.

Importing this module does nothing but define names: the engine exists only once
someone calls `configure()` with an explicit database URL. That is the seam that
lets the caller choose the database — the compose Postgres when serving, a
throwaway container when testing — instead of having it decided at import time.

Serving still needs no extra wiring: `get_engine()` falls back to
`settings.database_url` on first use, so `uvicorn app.main:app` behaves exactly
as it did. The fallback reads the environment when the first request arrives,
never at import.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def configure(database_url: str) -> Engine:
    """Point this process at `database_url`, replacing any previous engine."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(database_url, pool_pre_ping=True, future=True)
    _session_factory = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True
    )
    return _engine


def reset() -> None:
    """Drop the configured engine. Mainly for tests tearing a database down."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def is_configured() -> bool:
    return _engine is not None


def get_engine() -> Engine:
    if _engine is None:
        from .config import settings  # local import — keeps this module inert

        configure(settings.database_url)
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        get_engine()
    assert _session_factory is not None
    return _session_factory


def new_session() -> Session:
    """A session the caller owns and must close. Inside FastAPI use `get_db`."""
    return get_session_factory()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = new_session()
    try:
        yield db
    finally:
        db.close()
