"""Test fixtures: a disposable pgvector database and an HTTP client bound to it.

By default the suite starts a throwaway `pgvector/pgvector:pg16` container via
testcontainers, so `pytest` works from a clean checkout with nothing running but
Docker. Set `TEST_DATABASE_URL` to point at an existing database instead — every
table in it is dropped and rebuilt from the migrations, so never point it at
real data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

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


def _empty_the_database(eng: Engine) -> None:
    """Drop every table and enum type, so the migrations can run from zero.

    Migrations are not idempotent: against a database an earlier run left
    behind — or one the `create_all` this replaces built, which carries no
    `alembic_version` for `upgrade` to pick up from — 0001 would trip over
    tables that already exist.

    What is dropped comes from the catalogue rather than from `Base.metadata`,
    so a table the migrations create and the models never knew about goes too.
    Enum types need dropping by name because they outlive their tables and
    `CREATE TYPE` has no IF NOT EXISTS. Extensions and the schema itself are
    deliberately left alone: `vector` is not a trusted extension, so dropping
    it would make the next run need a superuser that the `create_all` harness
    never asked for.
    """
    with eng.begin() as conn:
        tables = conn.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        ).scalars().all()
        if tables:
            names = ", ".join(f'"{t}"' for t in tables)
            conn.execute(text(f"DROP TABLE {names} CASCADE"))

        enums = conn.execute(
            text(
                "SELECT t.typname FROM pg_type t "
                "JOIN pg_namespace n ON n.oid = t.typnamespace "
                "WHERE t.typtype = 'e' AND n.nspname = current_schema()"
            )
        ).scalars().all()
        for name in enums:
            conn.execute(text(f'DROP TYPE "{name}" CASCADE'))


def _build_schema(eng: Engine) -> None:
    """Build the schema by running the migrations, not `Base.metadata.create_all`.

    Whatever `alembic/versions/` produces is what the tests run against, so a
    model that has drifted from the migration history fails the suite instead
    of passing against a schema no deploy would ever produce.
    """
    from alembic import command
    from alembic.config import Config

    _empty_the_database(eng)

    # Built without the ini file: `alembic.ini` carries a `fileConfig` logging
    # section, and applying it here would disable every logger pytest and the
    # rest of the suite have already set up.
    cfg = Config()
    # Absolute, so the suite migrates the same tree whether pytest was started
    # from `backend/` or from the repo root.
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    # Taken off the engine rather than passed in alongside it, so there is no
    # second copy of the URL that could disagree with the database being wiped.
    cfg.attributes["db_url"] = eng.url.render_as_string(hide_password=False)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine(database_url):
    """Point the whole process at the throwaway database and build its schema."""
    eng = db_module.configure(database_url)
    _build_schema(eng)
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
