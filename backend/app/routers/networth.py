"""Net worth: current snapshot across all accounts + monthly history."""
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, Fund, FundKind, GoalType, NetWorthSnapshot
from ..month import current_month
from ..services.balances import fund_balance

router = APIRouter(prefix="/networth", tags=["networth"])


def _loan_debt(db: Session) -> Decimal:
    """Sum of remaining balances on debt funds (target owed − amount paid),
    clamped at 0. These are liabilities that reduce net worth."""
    funds = db.scalars(
        select(Fund).where(
            Fund.kind == FundKind.goal,
            Fund.goal_type == GoalType.debt,
            Fund.archived_at.is_(None),
        )
    ).all()
    total = Decimal("0")
    for f in funds:
        remaining = Decimal(f.target or 0) - fund_balance(db, f.id)
        if remaining > 0:
            total += remaining
    return total


def _compute(db: Session) -> dict:
    """Current breakdown by account type. Credit balances are subtracted as debt."""
    accts = db.scalars(select(Account).order_by(Account.id)).all()

    by_type: dict[str, Decimal] = {
        "checking": Decimal("0"), "savings": Decimal("0"),
        "investment": Decimal("0"), "credit": Decimal("0"),
        "emergency_fund": Decimal("0"),
    }
    rows = []
    for a in accts:
        bal = Decimal(a.current_balance)
        by_type[a.type.value] = by_type.get(a.type.value, Decimal("0")) + bal
        rows.append({
            "id": a.id,
            "name": a.name,
            "type": a.type.value,
            "balance": str(bal),
            "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
        })

    liquid = by_type["checking"] + by_type["savings"]
    investment = by_type["investment"]
    credit = by_type["credit"]
    emergency = by_type["emergency_fund"]
    loan = _loan_debt(db)
    total = liquid + investment + emergency - credit - loan

    return {
        "total": total, "liquid": liquid, "investment": investment,
        "emergency_fund": emergency, "credit_debt": credit, "loan_debt": loan,
        "by_type": by_type, "accounts": rows,
    }


def _upsert_snapshot(db: Session, vals: dict) -> None:
    """Idempotently store this month's snapshot (keyed by first-of-month)."""
    month = current_month()
    snap = db.get(NetWorthSnapshot, month)
    if snap is None:
        snap = NetWorthSnapshot(month=month)
        db.add(snap)
    snap.total = vals["total"]
    snap.liquid = vals["liquid"]
    snap.investment = vals["investment"]
    snap.emergency_fund = vals["emergency_fund"]
    snap.credit_debt = vals["credit_debt"]
    snap.loan_debt = vals["loan_debt"]
    db.commit()


@router.get("")
def networth(db: Session = Depends(get_db)):
    """Current breakdown by account type, and captures a monthly snapshot.

    Returns:
      liquid:     checking + savings  (cash you can spend)
      investment: IRAs / brokerage    (long-term)
      credit:     positive number     (debt — pulled out of total)
      total:      liquid + investment + emergency − credit
      accounts:   per-account rows
    """
    vals = _compute(db)
    _upsert_snapshot(db, vals)
    return {
        "total": str(vals["total"]),
        "liquid": str(vals["liquid"]),
        "investment": str(vals["investment"]),
        "emergency_fund": str(vals["emergency_fund"]),
        "credit_debt": str(vals["credit_debt"]),
        "loan_debt": str(vals["loan_debt"]),
        "by_type": {k: str(v) for k, v in vals["by_type"].items()},
        "accounts": vals["accounts"],
    }


@router.get("/history")
def networth_history(db: Session = Depends(get_db)):
    """Ordered monthly net-worth snapshots for the trend chart."""
    snaps = db.scalars(
        select(NetWorthSnapshot).order_by(NetWorthSnapshot.month)
    ).all()
    return [
        {
            "month": s.month.isoformat(),
            "total": str(s.total),
            "liquid": str(s.liquid),
            "investment": str(s.investment),
            "emergency_fund": str(s.emergency_fund),
            "credit_debt": str(s.credit_debt),
            "loan_debt": str(s.loan_debt),
        }
        for s in snaps
    ]
