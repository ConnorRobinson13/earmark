"""link accounts back to their plaid item

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("plaid_item_id", sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_accounts_plaid_item",
        "accounts", "plaid_items",
        ["plaid_item_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_accounts_plaid_item", "accounts", type_="foreignkey")
    op.drop_column("accounts", "plaid_item_id")
