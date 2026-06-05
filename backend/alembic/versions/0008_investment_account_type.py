"""add investment account type for IRAs, brokerage, 401k

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE must run outside a transaction.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'investment'")


def downgrade() -> None:
    # No-op: Postgres doesn't support removing values from an enum cleanly,
    # and any account rows already using 'investment' would break.
    pass
