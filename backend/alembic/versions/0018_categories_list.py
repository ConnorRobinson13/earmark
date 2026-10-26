"""categories become a managed list; funds point at one by id

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-26

Until now `funds.category` was free text, so the same group could be spelled
three ways. This creates a `categories` table, copies every distinct existing
name into it so no data is lost, points each fund at its row, and drops the
text column.

`downgrade` puts the text column back and copies each fund's category name
into it before dropping the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("funds", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "funds_category_id_fkey", "funds", "categories", ["category_id"], ["id"]
    )

    # Every distinct name already in use becomes a row, then each fund is linked.
    op.execute(
        """
        INSERT INTO categories (name)
        SELECT DISTINCT category FROM funds
        WHERE category IS NOT NULL AND category <> ''
        """
    )
    op.execute(
        """
        UPDATE funds SET category_id = categories.id
        FROM categories
        WHERE funds.category = categories.name
        """
    )
    op.drop_column("funds", "category")


def downgrade() -> None:
    op.add_column("funds", sa.Column("category", sa.String(60), nullable=True))
    op.execute(
        """
        UPDATE funds SET category = categories.name
        FROM categories
        WHERE funds.category_id = categories.id
        """
    )
    op.drop_constraint("funds_category_id_fkey", "funds", type_="foreignkey")
    op.drop_column("funds", "category_id")
    op.drop_table("categories")
