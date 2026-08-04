"""Net worth: what everything adds up to right now, and the monthly history.

Net worth is assets minus debts, where the assets are live account balances and
the debts come from two places — credit-card balances, and what is still owed on
debt funds. Spendable cash is *not* recomputed here: it comes from
`balances.liquid_cash`, the same definition the dashboard reads, so the two
views cannot drift apart.

Nothing in this module commits. Callers own the transaction boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, AccountType, Fund, FundKind, GoalType, NetWorthSnapshot
from ..month import current_month
from .balances import fund_balance, liquid_cash


@dataclass(frozen=True)
class NetWorth:
    """The current breakdown. Debts are held as positive numbers — `total` is
    the only place the signs are resolved, so the formula lives in one spot."""

    liquid: Decimal
    investment: Decimal
    emergency_fund: Decimal
    credit_debt: Decimal
    loan_debt: Decimal
    by_type: dict[str, Decimal]
    accounts: list[Account]

    @property
    def total(self) -> Decimal:
        return (
            self.liquid
            + self.investment
            + self.emergency_fund
            - self.credit_debt
            - self.loan_debt
        )


def remaining_debt(db: Session, fund: Fund) -> Decimal:
    """What is still owed on a debt fund: its target (the amount borrowed) less
    everything paid into it, floored at zero.

    The floor matters — a fund paid past its target is settled, and letting it
    go negative would turn a closed loan into an asset.
    """
    owed = Decimal(fund.target or 0) - fund_balance(db, fund.id)
    return owed if owed > 0 else Decimal("0")


def total_remaining_debt(db: Session) -> Decimal:
    """Everything still owed across active debt funds — the liability side of
    net worth that credit cards don't cover (car loans, student loans, ...).

    Archived funds are left out for the same reason they are elsewhere: a real
    fund is swept to zero before archiving, and the hidden "[History]" funds
    carrying imported history must never move current numbers.
    """
    funds = db.scalars(
        select(Fund).where(
            Fund.kind == FundKind.goal,
            Fund.goal_type == GoalType.debt,
            Fund.archived_at.is_(None),
        )
    ).all()
    return sum((remaining_debt(db, f) for f in funds), Decimal("0"))


def compute_net_worth(db: Session) -> NetWorth:
    """Current net worth, broken down by account type plus debt funds."""
    accounts = list(db.scalars(select(Account).order_by(Account.id)).all())

    # Seeded from the enum rather than from the accounts present, so the
    # breakdown keeps its full set of keys on a thin (or empty) database.
    by_type: dict[str, Decimal] = {t.value: Decimal("0") for t in AccountType}
    for a in accounts:
        by_type[a.type.value] = by_type.get(a.type.value, Decimal("0")) + Decimal(
            a.current_balance
        )

    return NetWorth(
        liquid=liquid_cash(db),
        investment=by_type[AccountType.investment.value],
        emergency_fund=by_type[AccountType.emergency_fund.value],
        credit_debt=by_type[AccountType.credit.value],
        loan_debt=total_remaining_debt(db),
        by_type=by_type,
        accounts=accounts,
    )


def capture_snapshot(db: Session) -> NetWorthSnapshot:
    """Record today's net worth against this month, replacing the month's row if
    one is already there — the chart wants one point per month, and the latest
    reading is the one worth keeping.

    Flushes but does not commit: this is a write, so the caller decides when it
    lands.
    """
    first = current_month()
    nw = compute_net_worth(db)

    snap = db.get(NetWorthSnapshot, first)
    if snap is None:
        snap = NetWorthSnapshot(month=first)
        db.add(snap)
    snap.total = nw.total
    snap.liquid = nw.liquid
    snap.investment = nw.investment
    snap.emergency_fund = nw.emergency_fund
    snap.credit_debt = nw.credit_debt
    snap.loan_debt = nw.loan_debt
    db.flush()
    return snap


def snapshot_history(db: Session) -> list[NetWorthSnapshot]:
    """Every recorded snapshot, oldest first — the trend chart's x-axis."""
    return list(
        db.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.month)).all()
    )
