"""The migrations and `app/models.py` must describe the same schema.

Nothing else in the repo checks this. The app reads and writes through the
models, while every deployed database is built by `alembic/versions/`, so a
column added to one and not the other is a bug that only shows up as a runtime
`UndefinedColumn` against the compose stack. Here it is a failing test.

The check is alembic's own autogenerate comparison, pointed at the migrated
database in the `engine` fixture: if autogenerate can find anything to write,
the two have drifted. It catches tables, columns, types, nullability, indexes
and constraints — see the comment below for the one thing it deliberately
does not compare.
"""
from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app import db as db_module
from app import models  # noqa: F401 — registers tables on Base.metadata


def test_models_and_migrations_agree(engine):
    with engine.connect() as conn:
        # Types are compared; server defaults are not. Seven columns here carry
        # a `server_default` in the migration and a Python-side `default` in the
        # model — deliberate, since the app inserts through the ORM and the
        # server default is only a backstop for raw SQL — and alembic reports
        # every one of them as a difference. Turning the comparison on would
        # cost seven `server_default=` declarations in the models to buy a
        # narrow class of drift, so it stays off.
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = compare_metadata(context, db_module.Base.metadata)

    assert diffs == [], (
        "app/models.py and alembic/versions/ have drifted. Autogenerate would "
        f"emit: {diffs}"
    )
