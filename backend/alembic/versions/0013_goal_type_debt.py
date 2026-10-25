"""add 'debt' to the goaltype enum — payoff funds that count down from a balance owed

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE goaltype ADD VALUE IF NOT EXISTS 'debt'")


def downgrade() -> None:
    # Postgres can't drop a single enum value; leaving 'debt' in place is harmless.
    pass
