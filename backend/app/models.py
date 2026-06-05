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
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .db import Base


class GoalType(str, enum.Enum):
    savings = "savings"           # target = a balance you want to hit
    contribution = "contribution" # target = total contributed in a period (Roth/HSA/401k)
    debt = "debt"                 # target = amount owed; money added pays it DOWN toward 0


class FundKind(str, enum.Enum):
    operational = "operational"
    goal = "goal"


class TxType(str, enum.Enum):
    expense = "expense"
    income = "income"
    transfer = "transfer"
    assignment = "assignment"


class AccountType(str, enum.Enum):
    investment = "investment"      # IRA / 401k / brokerage — balance-tracked, no inbox
    emergency_fund = "emergency_fund"  # savings carved out from "spendable cash"
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
    goal_type: Mapped[Optional[GoalType]] = mapped_column(
        Enum(GoalType), nullable=True
    )  # set only when kind=goal
    backed_by_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("accounts.id"), nullable=True
    )
    # For debt funds: the actual fixed monthly payment from the lender (includes
    # interest). When set, the UI shows this instead of the principal-only
    # payoff-by-date estimate.
    min_payment: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    # Day-of-month (1-31) the fund's spending/bill is due. Recurs every month;
    # clamped to the month length at projection time (31 -> Feb 28). Drives the
    # cash-flow timeline. Defaults to the 1st.
    due_day: Mapped[int] = mapped_column(
        SmallInteger, default=1, server_default="1", nullable=False
    )
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
    plaid_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("plaid_items.id", ondelete="SET NULL"), nullable=True
    )


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


class MonthlyMeta(Base):
    """Per-month planning numbers. Today this is just the expected income for
    the month; Unassigned is computed against this figure (EveryDollar-style)
    rather than against actual deposits, so paychecks landing don't bump
    Unassigned — they were already allocated in the plan."""
    __tablename__ = "monthly_meta"

    month: Mapped[date] = mapped_column(Date, primary_key=True)
    planned_income: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GoalSettlement(Base):
    """A real-world money move from one account to another, tagged to a goal.

    Created when the user clicks "Mark moved" on a goal at month end. Bumps
    `from_account_id` down and `to_account_id` up by `amount`. The goal's
    fund balance is untouched (assignments already credited it earlier in the
    month); this row is what `goals_saved_in_month` reads from.
    """
    __tablename__ = "goal_settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("funds.id", ondelete="CASCADE"))
    from_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    to_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    settled_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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


class PaydaySchedule(Base):
    """A recurring payday. Drives the cash-flow projection's expected income.

    `day_of_month` (1-31) is clamped to the month length at projection time.
    `amount` is the deposit for this payday; if NULL, the payday receives an
    even split of the month's planned income across all NULL-amount paydays
    (fixed-amount paydays are subtracted from planned income first).
    """
    __tablename__ = "payday_schedule"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_of_month: Mapped[int] = mapped_column(SmallInteger)
    amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NetWorthSnapshot(Base):
    """One row per month capturing the net-worth breakdown, so the Net Worth view
    can chart a trend over time. Keyed by the first day of the month; re-computed
    idempotently (upserted) whenever the net-worth endpoint is hit."""

    __tablename__ = "networth_snapshots"

    month: Mapped[date] = mapped_column(Date, primary_key=True)  # first of month
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    liquid: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    investment: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    emergency_fund: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    credit_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    loan_debt: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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
