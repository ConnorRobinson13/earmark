"""add loan_debt to networth_snapshots — debt-fund balances reduce net worth

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "networth_snapshots",
        sa.Column("loan_debt", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("networth_snapshots", "loan_debt")
