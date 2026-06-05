"""Cash-flow timeline: project liquid cash day-by-day through a month."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.balances import project_cashflow

router = APIRouter(prefix="/cashflow", tags=["cashflow"])


@router.get("")
def cashflow(
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
    return project_cashflow(db, month_date)
