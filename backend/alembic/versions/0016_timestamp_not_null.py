"""make the timestamp columns NOT NULL, as the models always said they were

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-03

Every one of these columns is non-Optional in `app/models.py` and carries a
`server_default` of now(), so nothing has ever meant to write a NULL into them.
The migrations that created them simply omitted `nullable=False` — 0001 did not.
Nothing broke because the default fills the column on every insert the app
makes; the columns were just wider than the model believed.

Backfilled before the ALTER because a row inserted with an explicit NULL would
otherwise fail the constraint and take the whole upgrade down with it.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS: tuple[tuple[str, str], ...] = (
    ("goal_settlements", "created_at"),
    ("monthly_meta", "created_at"),
    ("monthly_meta", "updated_at"),
    ("networth_snapshots", "updated_at"),
    ("payday_schedule", "created_at"),
)


def upgrade() -> None:
    for table, column in COLUMNS:
        op.execute(f"UPDATE {table} SET {column} = now() WHERE {column} IS NULL")
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.func.now(),
            nullable=False,
        )


def downgrade() -> None:
    for table, column in COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.DateTime(timezone=True),
            existing_server_default=sa.func.now(),
            nullable=True,
        )
