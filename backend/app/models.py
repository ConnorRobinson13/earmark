from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Date,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .db import Base


class FundKind(str, enum.Enum):
    operational = "operational"
    goal = "goal"


class TxType(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"
    assignment = "assignment"


class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"


class InboxStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Fund(Base):
    __tablename__ = "funds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[FundKind] = mapped_column(Enum(FundKind), default=FundKind.operational)
    target: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    backed_by_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Per-month visibility: if set, this fund only appears in months whose
    # start day is <= effective_to_month. Used by "delete from this month" so
    # past months keep the fund while future months don't.
    effective_to_month: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="fund")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    type: Mapped[AccountType] = mapped_column(Enum(AccountType))
    current_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    plaid_account_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[Optional[int]] = mapped_column(ForeignKey("funds.id"), nullable=True)
    type: Mapped[TxType] = mapped_column(Enum(TxType))
    # Signed amount: negative for outflow from fund, positive for inflow.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date] = mapped_column(Date)
    merchant: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plaid_transaction_id: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, unique=True
    )
    linked_transaction_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    fund: Mapped[Optional[Fund]] = relationship(back_populates="transactions")


class MonthlyTemplate(Base):
    __tablename__ = "monthly_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"))
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))


class PlaidInbox(Base):
    __tablename__ = "plaid_inbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    plaid_transaction_id: Mapped[str] = mapped_column(String(120), unique=True)
    raw: Mapped[dict] = mapped_column(JSONB)
    merchant: Mapped[str] = mapped_column(String(200), default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    date: Mapped[date] = mapped_column(Date)
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    suggested_fund_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("funds.id"), nullable=True
    )
    status: Mapped[InboxStatus] = mapped_column(Enum(InboxStatus), default=InboxStatus.pending)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PlaidItem(Base):
    """A linked Plaid Item (one per institution login)."""

    __tablename__ = "plaid_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[str] = mapped_column(String(120), unique=True)
    access_token: Mapped[str] = mapped_column(String(200))
    institution_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    cursor: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
