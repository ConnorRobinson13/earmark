"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1024  # mxbai-embed-large


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    fund_kind = sa.Enum("operational", "goal", name="fundkind")
    tx_type = sa.Enum("expense", "income", "transfer", "assignment", name="txtype")
    acct_type = sa.Enum("checking", "savings", "credit", name="accounttype")
    inbox_status = sa.Enum("pending", "approved", "rejected", name="inboxstatus")

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("type", acct_type, nullable=False),
        sa.Column("current_balance", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("plaid_account_id", sa.String(120)),
    )

    op.create_table(
        "funds",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("kind", fund_kind, nullable=False, server_default="operational"),
        sa.Column("target", sa.Numeric(12, 2)),
        sa.Column("target_date", sa.Date),
        sa.Column("backed_by_account_id", sa.Integer, sa.ForeignKey("accounts.id")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fund_id", sa.Integer, sa.ForeignKey("funds.id")),
        sa.Column("type", tx_type, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("merchant", sa.String(200), nullable=False, server_default=""),
        sa.Column("notes", sa.Text),
        sa.Column("plaid_transaction_id", sa.String(120), unique=True),
        sa.Column("linked_transaction_id", sa.Integer, sa.ForeignKey("transactions.id")),
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_transactions_date", "transactions", ["date"])
    op.create_index("ix_transactions_fund_id", "transactions", ["fund_id"])

    op.create_table(
        "monthly_templates",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fund_id", sa.Integer, sa.ForeignKey("funds.id"), nullable=False),
        sa.Column("planned_amount", sa.Numeric(12, 2), nullable=False),
    )

    op.create_table(
        "plaid_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("item_id", sa.String(120), nullable=False, unique=True),
        sa.Column("access_token", sa.String(200), nullable=False),
        sa.Column("institution_name", sa.String(200)),
        sa.Column("cursor", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "plaid_inbox",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plaid_transaction_id", sa.String(120), nullable=False, unique=True),
        sa.Column("raw", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("merchant", sa.String(200), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("account_id", sa.Integer, sa.ForeignKey("accounts.id")),
        sa.Column("suggested_fund_id", sa.Integer, sa.ForeignKey("funds.id")),
        sa.Column("status", inbox_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("plaid_inbox")
    op.drop_table("plaid_items")
    op.drop_table("monthly_templates")
    op.drop_index("ix_transactions_fund_id", table_name="transactions")
    op.drop_index("ix_transactions_date", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("funds")
    op.drop_table("accounts")
    for name in ("inboxstatus", "accounttype", "txtype", "fundkind"):
        op.execute(f"DROP TYPE IF EXISTS {name}")
