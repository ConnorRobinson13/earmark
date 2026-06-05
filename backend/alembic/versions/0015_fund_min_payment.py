"""add funds.min_payment — fixed monthly payment for debt funds (incl. interest)

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("funds", sa.Column("min_payment", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("funds", "min_payment")
