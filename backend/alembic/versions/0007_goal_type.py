"""distinguish savings goals from contribution goals (Roth/HSA/401k)

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE goaltype AS ENUM ('savings', 'contribution')")
    op.add_column(
        "funds",
        sa.Column(
            "goal_type",
            sa.Enum("savings", "contribution", name="goaltype", create_type=False),
            nullable=True,
        ),
    )
    # Backfill: any existing goal fund defaults to 'savings'
    op.execute("UPDATE funds SET goal_type = 'savings' WHERE kind = 'goal'")


def downgrade() -> None:
    op.drop_column("funds", "goal_type")
    op.execute("DROP TYPE goaltype")
