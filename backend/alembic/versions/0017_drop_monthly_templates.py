"""drop monthly_templates — the planner is gone

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-05

The Planner view, the `/templates` endpoints and the `MonthlyTemplate` model
were removed together; this drops the table they shared. Nothing else reads it —
the fixed-expense plan it held was only ever applied through `POST
/templates/apply`, which turned each row into an ordinary assignment. Those
assignments are transactions and are untouched.

`downgrade` recreates the table but cannot recreate its contents. The rows that
were in it when the planner was removed are in
`backups/monthly_templates-before-removal-20260805-205119.sql` as column-wise
INSERTs, replayable once the table exists again.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("monthly_templates")


def downgrade() -> None:
    op.create_table(
        "monthly_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fund_id", sa.Integer(), nullable=False),
        sa.Column("planned_amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["fund_id"], ["funds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
