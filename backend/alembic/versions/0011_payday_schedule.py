"""add payday_schedule — recurring paydays driving the cash-flow projection

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "payday_schedule",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("day_of_month", sa.SmallInteger, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("payday_schedule")
