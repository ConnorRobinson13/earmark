"""goal settlements — record month-end "money moved" to backing accounts

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "goal_settlements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("goal_id", sa.Integer, sa.ForeignKey("funds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("to_account_id", sa.Integer, sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("settled_at", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_goal_settlements_goal_month", "goal_settlements", ["goal_id", "settled_at"])


def downgrade() -> None:
    op.drop_index("ix_goal_settlements_goal_month", table_name="goal_settlements")
    op.drop_table("goal_settlements")
