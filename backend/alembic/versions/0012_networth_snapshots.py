"""add networth_snapshots — monthly net-worth history for the trend chart

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "networth_snapshots",
        sa.Column("month", sa.Date, primary_key=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=False),
        sa.Column("liquid", sa.Numeric(14, 2), nullable=False),
        sa.Column("investment", sa.Numeric(14, 2), nullable=False),
        sa.Column("emergency_fund", sa.Numeric(14, 2), nullable=False),
        sa.Column("credit_debt", sa.Numeric(14, 2), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("networth_snapshots")
