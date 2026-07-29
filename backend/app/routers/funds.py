from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Fund, Transaction
from ..month import parse_month
from ..services import transactions as tx_svc
from ..services.account_sync import sync_goals_for_account
from ..services.balances import enrich_fund, fund_balance

router = APIRouter(prefix="/funds", tags=["funds"])


@router.get("", response_model=list[schemas.FundOut])
def list_funds(include_archived: bool = False, db: Session = Depends(get_db)):
    q = select(Fund)
    if not include_archived:
        q = q.where(Fund.archived_at.is_(None))
    q = q.order_by(Fund.sort_order, Fund.id)
    return [enrich_fund(db, f) for f in db.scalars(q).all()]


@router.post("", response_model=schemas.FundOut, status_code=201)
def create_fund(body: schemas.FundCreate, db: Session = Depends(get_db)):
    f = Fund(**body.model_dump())
    db.add(f)
    db.commit()
    db.refresh(f)
    return enrich_fund(db, f)


@router.get("/{fund_id}", response_model=schemas.FundOut)
def get_fund(fund_id: int, db: Session = Depends(get_db)):
    f = db.get(Fund, fund_id)
    if not f:
        raise HTTPException(404)
    return enrich_fund(db, f)


@router.patch("/{fund_id}", response_model=schemas.FundOut)
def update_fund(fund_id: int, body: schemas.FundUpdate, db: Session = Depends(get_db)):
    f = db.get(Fund, fund_id)
    if not f:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if "archived" in data:
        f.archived_at = datetime.now(timezone.utc) if data.pop("archived") else None
    backing_changed = "backed_by_account_id" in data
    for k, v in data.items():
        setattr(f, k, v)
    db.flush()
    # If this is a goal newly linked to an account, sync its balance to match.
    if backing_changed and f.backed_by_account_id is not None and f.kind.value == "goal":
        sync_goals_for_account(db, f.backed_by_account_id)
    db.commit()
    db.refresh(f)
    return enrich_fund(db, f)


@router.delete("/{fund_id}")
def archive_fund(
    fund_id: int,
    month: str | None = Query(None, description="YYYY-MM or YYYY-MM-DD — if set, end the fund from this month forward only"),
    db: Session = Depends(get_db),
):
    """Delete a fund.

    Without `month`: full global archive. Any non-zero balance sweeps to Unassigned today.

    With `month`: end the fund effective from that month forward. Prior months keep
    the fund and all history intact. All transactions for the fund dated >= month
    start (and their linked counterparts) are deleted, and the fund's balance at
    end of the prior month is swept to Unassigned dated the prior day.
    """
    f = db.get(Fund, fund_id)
    if not f:
        raise HTTPException(404)

    if month is None:
        # legacy global archive
        bal = fund_balance(db, f.id)
        swept = 0
        if bal != 0:
            tx_svc.post_assignment(
                db, fund_id=f.id, amount=-bal,
                txn_date=date.today(), notes="Swept on archive",
            )
            swept = bal
        f.archived_at = datetime.now(timezone.utc)
        db.commit()
        return {"archived": True, "swept_to_unassigned": str(swept)}

    # per-month end
    month_start = parse_month(month)
    prior_day = month_start - timedelta(days=1)

    # Sweep balance as of end-of-prior-month back to Unassigned, dated prior_day
    bal = fund_balance(db, f.id, as_of=prior_day)
    swept = 0
    if bal != 0:
        tx_svc.post_assignment(
            db, fund_id=f.id, amount=-bal,
            txn_date=prior_day, notes=f"Swept on end-of-month {prior_day}",
        )
        swept = bal

    # Delete all transactions for this fund dated >= month_start AND their linked counterparts.
    # Two-step: collect IDs, NULL the FK back-refs (so the self-referential FK constraint
    # doesn't fire when we delete pairs), then delete.
    txns = db.scalars(
        select(Transaction).where(
            Transaction.fund_id == f.id,
            Transaction.date >= month_start,
        )
    ).all()
    ids_to_delete: set[int] = set()
    for t in txns:
        ids_to_delete.add(t.id)
        if t.linked_transaction_id:
            ids_to_delete.add(t.linked_transaction_id)
    deleted = 0
    if ids_to_delete:
        db.execute(
            update(Transaction)
            .where(Transaction.id.in_(ids_to_delete))
            .values(linked_transaction_id=None)
        )
        db.flush()
        for tid in ids_to_delete:
            obj = db.get(Transaction, tid)
            if obj is not None:
                db.delete(obj)
                deleted += 1

    f.effective_to_month = prior_day
    db.commit()
    return {
        "ended_after": prior_day.isoformat(),
        "swept_to_unassigned": str(swept),
        "transactions_deleted": deleted,
    }
