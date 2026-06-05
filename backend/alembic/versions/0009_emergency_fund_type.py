"""add emergency_fund account type — savings earmarked away from spendable cash

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE accounttype ADD VALUE IF NOT EXISTS 'emergency_fund'")


def downgrade() -> None:
    pass
