"""Balance computation for funds and the unassigned pool.

All "this month" helpers accept an explicit `month` (any date in the target month);
when omitted they default to today's month. This lets the dashboard time-travel
backward (historical snapshots) or forward (planning view) without changing the
underlying data.

A fund's balance is the signed sum of all its transactions through `as_of`
(inclusive). For a past month view we pass as_of = last day of that month so
the balance reflects a historical snapshot.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Fund, Transaction


def month_bounds(d: date) -> tuple[date, date]:
    """Return (first_of_month, first_of_next_month) — last is exclusive upper bound."""
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt


def fund_balance(db: Session, fund_id: int, as_of: date | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.fund_id == fund_id
    )
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    return Decimal(db.scalar(q) or 0)


def fund_net_spent_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Net outflows for a fund within `month`, positive when net spent.

    Includes expense, transfer, AND tagged income — so reimbursements offset spending.
    Assignments are excluded since they are budgeting, not spending.
    """
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type.in_(["expense", "transfer", "income"]),
        )
    )
    return -Decimal(total or 0)


def fund_assigned_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Sum of assignment entries on this fund within `month`."""
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type == "assignment",
        )
    )
    return Decimal(total or 0)


def fund_balance_at_month_start(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Fund balance carried into `month` (sum of transactions before its first day)."""
    first, _ = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date < first,
        )
    )
    return Decimal(total or 0)


def fund_available_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Rollover + this month's assignment."""
    return fund_balance_at_month_start(db, fund_id, month) + fund_assigned_in_month(
        db, fund_id, month
    )


def untagged_income_in_month(db: Session, month: date | None = None) -> Decimal:
    """Total income landing in Unassigned (untagged) for the given month."""
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id.is_(None),
            Transaction.type == "income",
            Transaction.date >= first,
            Transaction.date < nxt,
        )
    )
    return Decimal(total or 0)


def unassigned_balance(db: Session, as_of: date | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.fund_id.is_(None)
    )
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    return Decimal(db.scalar(q) or 0)


def all_funds_total(db: Session, as_of: date | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.fund_id.is_not(None)
    )
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    return Decimal(db.scalar(q) or 0)


def enrich_fund(db: Session, f: Fund, month: date | None = None) -> dict:
    month = month or date.today()
    _, nxt = month_bounds(month)
    as_of = nxt - timedelta(days=1)  # last day of selected month
    return {
        "id": f.id,
        "name": f.name,
        "kind": f.kind,
        "target": f.target,
        "target_date": f.target_date,
        "backed_by_account_id": f.backed_by_account_id,
        "sort_order": f.sort_order,
        "category": f.category,
        "archived_at": f.archived_at,
        "balance": fund_balance(db, f.id, as_of=as_of),
        "net_spent_this_month": fund_net_spent_in_month(db, f.id, month),
        "assigned_this_month": fund_assigned_in_month(db, f.id, month),
        "available_this_month": fund_available_in_month(db, f.id, month),
    }
