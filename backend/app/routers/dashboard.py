from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Account, AccountType, Fund
from ..services.balances import (
    all_funds_total,
    enrich_fund,
    month_bounds,
    unassigned_balance,
    untagged_income_in_month,
)

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=schemas.DashboardOut)
def dashboard(
    month: str | None = Query(None, description="YYYY-MM or YYYY-MM-DD; defaults to current month"),
    db: Session = Depends(get_db),
):
    if month:
        try:
            month_date = date.fromisoformat(month + "-01" if len(month) == 7 else month)
        except ValueError:
            raise HTTPException(400, "month must be YYYY-MM or YYYY-MM-DD")
    else:
        month_date = date.today()
    month_first, nxt = month_bounds(month_date)
    as_of = nxt - timedelta(days=1)
    # liquid cash = checking + savings; credit cards = what you owe.
    liquid = db.scalar(
        select(func.coalesce(func.sum(Account.current_balance), 0)).where(
            Account.type.in_([AccountType.checking, AccountType.savings])
        )
    )
    credit_owed = db.scalar(
        select(func.coalesce(func.sum(Account.current_balance), 0)).where(
            Account.type == AccountType.credit
        )
    )
    funds = db.scalars(
        select(Fund).where(
            Fund.archived_at.is_(None),
            Fund.created_at < nxt,
            (Fund.effective_to_month.is_(None)) | (Fund.effective_to_month >= month_first),
        ).order_by(Fund.sort_order, Fund.id)
    ).all()
    enriched = [enrich_fund(db, f, month=month_first) for f in funds]
    spent = sum((Decimal(f["net_spent_this_month"]) for f in enriched), Decimal("0"))
    liquid_d = Decimal(liquid or 0)
    credit_d = Decimal(credit_owed or 0)
    return {
        "liquid_total": liquid_d,  # account balances are live, not month-scoped
        "credit_owed": credit_d,
        "net_cash": liquid_d - credit_d,
        "unassigned": unassigned_balance(db, as_of=as_of),
        "funds_total": all_funds_total(db, as_of=as_of),
        "spent_this_month": spent,
        "income_this_month": untagged_income_in_month(db, month_first),
        "month": month_first.isoformat(),
        "funds": enriched,
    }
