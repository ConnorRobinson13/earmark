"""Test fixtures: a disposable pgvector database and an HTTP client bound to it.

By default the suite starts a throwaway `pgvector/pgvector:pg16` container via
testcontainers, so `pytest` works from a clean checkout with nothing running but
Docker. Set `TEST_DATABASE_URL` to point at an existing database instead — its
public schema is dropped and rebuilt from the migrations, so never point it at
real data.
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


def _build_schema(eng, url: str) -> None:
    """Build the schema by running the migrations, not `Base.metadata.create_all`.

    Whatever `alembic/versions/` produces is what the tests run against, so a
    model that has drifted from the migration history fails the suite here
    instead of passing against a schema no deploy would ever produce.

    The public schema is dropped first because migrations are not idempotent:
    against a database left over from an earlier run — or built by the
    `create_all` this replaces — `upgrade head` would trip over tables that
    already exist. Starting from nothing also means the run is reproducible,
    which is the whole point of asserting no drift against it. Safe only
    because this database is disposable by contract: `clean_db` already
    truncates every table in it between tests.
    """
    from alembic import command
    from alembic.config import Config

    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    # Built without the ini file: `alembic.ini` carries a `fileConfig` logging
    # section, and applying it here would disable every logger pytest and the
    # rest of the suite have already set up.
    cfg = Config()
    # Absolute, so the suite migrates the same tree whether pytest was started
    # from `backend/` or from the repo root.
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["db_url"] = url
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine(database_url):
    """Point the whole process at the throwaway database and build its schema."""
    eng = db_module.configure(database_url)
    _build_schema(eng, database_url)
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
