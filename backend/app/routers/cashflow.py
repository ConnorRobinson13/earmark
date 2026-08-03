"""Cash-flow timeline: project liquid cash day-by-day through a month."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..month import parse_month_or_current
from ..services.balances import gather_cashflow_inputs
from ..services.cashflow import CashflowPlan, project

router = APIRouter(prefix="/cashflow", tags=["cashflow"])


@router.get("", response_model=CashflowPlan)
def cashflow(
    month: str | None = Query(None, description="YYYY-MM or YYYY-MM-DD; defaults to current month"),
    db: Session = Depends(get_db),
):
    # Gather, then project: the session stops here, and the arithmetic behind
    # the plan never sees it.
    return project(gather_cashflow_inputs(db, parse_month_or_current(month)))
