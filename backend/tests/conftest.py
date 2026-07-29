"""Test fixtures: a disposable pgvector database and an HTTP client bound to it.

By default the suite starts a throwaway `pgvector/pgvector:pg16` container via
testcontainers, so `pytest` works from a clean checkout with nothing running but
Docker. Set `TEST_DATABASE_URL` to point at an existing database instead — the
schema is created into whatever it names, so never point it at real data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

# So `pytest backend/tests` works from the repo root too, not just `cd backend`.
BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# Keep the best-effort embedding client from reaching for Ollama during tests:
# an unroutable port fails instantly instead of burning the 10s HTTP timeout.
os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:1")

from app import db as db_module  # noqa: E402
from app import models  # noqa: E402,F401 — registers tables on Base.metadata

TEST_IMAGE = "pgvector/pgvector:pg16"


@pytest.fixture(scope="session", autouse=True)
def _no_accidental_fallback():
    """Make un-fixtured database access fail loudly.

    `get_engine()` falls back to `settings.database_url` when nothing has been
    configured — which on a dev box is the real budget database. Claiming the
    seam up front with a URL that cannot resolve means a test that forgets the
    `client` fixture errors out instead of quietly reading (or, via `clean_db`,
    truncating) real data.
    """
    db_module.configure("postgresql+psycopg://tests-must-use-the-client-fixture/")
    yield
    db_module.reset()


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return

    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - dev dependency missing
        pytest.fail(
            "testcontainers is not installed. Run "
            "`pip install -r requirements-dev.txt`, or set TEST_DATABASE_URL "
            "to an existing throwaway database."
        )

    with PostgresContainer(TEST_IMAGE, driver="psycopg") as container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def engine(database_url):
    """Point the whole process at the throwaway database and create the schema."""
    eng = db_module.configure(database_url)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    db_module.Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        db_module.reset()


@pytest.fixture()
def clean_db(engine):
    """Empty every table before each test so ordering can't leak state."""
    tables = ", ".join(t.name for t in db_module.Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def client(clean_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
