"""Cash-flow timeline: project liquid cash day-by-day through a month."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..month import parse_month_or_current
from ..services.balances import project_cashflow

router = APIRouter(prefix="/cashflow", tags=["cashflow"])


@router.get("")
def cashflow(
    month: str | None = Query(None, description="YYYY-MM or YYYY-MM-DD; defaults to current month"),
    db: Session = Depends(get_db),
):
    return project_cashflow(db, parse_month_or_current(month))
