"""add emergency_fund account type — savings earmarked away from spendable cash

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'emergency_fund'")


def downgrade() -> None:
    pass
