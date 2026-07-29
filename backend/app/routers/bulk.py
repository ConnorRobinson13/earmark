"""Bulk operations across funds — e.g. copying assignments month-to-month."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Fund
from ..month import is_current_month, next_month, parse_month
from ..services import transactions as tx_svc
from ..services.balances import (
    fund_assigned_in_month,
    untagged_income_in_month,
)

router = APIRouter(prefix="/bulk", tags=["bulk"])


class CopyAssignmentsBody(BaseModel):
    from_month: str  # YYYY-MM or YYYY-MM-DD
    to_month: str    # YYYY-MM or YYYY-MM-DD


class SetIncomeBody(BaseModel):
    month: str
    amount: Decimal


@router.post("/copy-assignments")
def copy_assignments(body: CopyAssignmentsBody, db: Session = Depends(get_db)):
    """Make `to_month`'s per-fund assignment totals equal `from_month`'s.

    Also resurrects any funds that were active in `from_month` but have since been
    archived — they come back with the source month's assigned amount. Posts a
    single delta assignment per fund (positive or negative) so the net assigned in
    `to_month` matches `from_month`. Idempotent.
    """
    src = parse_month(body.from_month)
    dst = parse_month(body.to_month)

    # Backdate the posting to the target month, unless that month is the current
    # one — then it belongs on today, so the ledger reads chronologically.
    post_date = date.today() if is_current_month(dst) else dst

    src_end = next_month(src)

    # Funds active during source month: created before end of src AND (not globally archived OR archived after src end) AND (no effective_to OR effective_to >= src first)
    funds = db.scalars(
        select(Fund).where(
            Fund.created_at < src_end,
            (Fund.archived_at.is_(None)) | (Fund.archived_at >= src_end),
            (Fund.effective_to_month.is_(None)) | (Fund.effective_to_month >= src),
        )
    ).all()

    # Resurrect: clear global archive AND extend effective_to_month so they show in dst.
    resurrected = 0
    for f in funds:
        bumped = False
        if f.archived_at is not None:
            f.archived_at = None
            bumped = True
        if f.effective_to_month is not None and f.effective_to_month < dst:
            f.effective_to_month = None
            bumped = True
        if bumped:
            resurrected += 1
    db.flush()
    updated = 0
    total_moved = Decimal("0")
    for f in funds:
        src_amt = fund_assigned_in_month(db, f.id, src)
        dst_amt = fund_assigned_in_month(db, f.id, dst)
        delta = src_amt - dst_amt
        if delta == 0:
            continue
        tx_svc.post_assignment(
            db,
            fund_id=f.id,
            amount=delta,
            txn_date=post_date,
            notes=f"Copied from {src.isoformat()}",
        )
        updated += 1
        total_moved += abs(delta)

    db.commit()
    return {
        "funds_updated": updated,
        "funds_resurrected": resurrected,
        "total_moved": str(total_moved),
        "from_month": src.isoformat(),
        "to_month": dst.isoformat(),
    }


@router.post("/set-monthly-income")
def set_monthly_income(body: SetIncomeBody, db: Session = Depends(get_db)):
    """Make total untagged income for `month` equal `amount` by posting a delta."""
    month = parse_month(body.month)
    post_date = date.today() if is_current_month(month) else month

    current = untagged_income_in_month(db, month)
    delta = body.amount - current
    if delta == 0:
        return {"delta": "0", "current": str(current), "target": str(body.amount)}
    tx_svc.post_income_signed(
        db,
        fund_id=None,
        amount=delta,
        txn_date=post_date,
        merchant="Income adjustment",
    )
    db.commit()
    return {"delta": str(delta), "current": str(body.amount), "target": str(body.amount)}
