from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import InboxStatus, PlaidInbox
from ..services import transactions as tx_svc
from ..services.suggest import suggest_fund

router = APIRouter(prefix="/inbox", tags=["inbox"])


@router.get("", response_model=list[schemas.InboxItemOut])
def list_inbox(db: Session = Depends(get_db)):
    return db.scalars(
        select(PlaidInbox)
        .where(PlaidInbox.status == InboxStatus.pending)
        .order_by(PlaidInbox.date.desc(), PlaidInbox.id.desc())
    ).all()


@router.post("/{inbox_id}/approve", response_model=schemas.TransactionOut)
def approve(inbox_id: int, body: schemas.InboxApprove, db: Session = Depends(get_db)):
    item = db.get(PlaidInbox, inbox_id)
    if not item or item.status != InboxStatus.pending:
        raise HTTPException(404)
    fund_id = body.fund_id or item.suggested_fund_id
    if fund_id is None:
        raise HTTPException(400, "no fund chosen and no suggestion available")

    # Plaid signs purchases positive; treat any positive amount as expense, negative as income.
    if item.amount >= 0:
        t = tx_svc.post_expense(
            db,
            fund_id=fund_id,
            amount=item.amount,
            txn_date=item.date,
            merchant=item.merchant,
            plaid_transaction_id=item.plaid_transaction_id,
        )
    else:
        t = tx_svc.post_income(
            db,
            fund_id=fund_id,
            amount=-item.amount,
            txn_date=item.date,
            merchant=item.merchant,
            plaid_transaction_id=item.plaid_transaction_id,
        )

    item.status = InboxStatus.approved
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(t)
    return t


@router.post("/{inbox_id}/reject", status_code=204)
def reject(inbox_id: int, db: Session = Depends(get_db)):
    item = db.get(PlaidInbox, inbox_id)
    if not item:
        raise HTTPException(404)
    item.status = InboxStatus.rejected
    item.reviewed_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/{inbox_id}/resuggest", response_model=schemas.InboxItemOut)
def resuggest(inbox_id: int, db: Session = Depends(get_db)):
    item = db.get(PlaidInbox, inbox_id)
    if not item:
        raise HTTPException(404)
    fund_id, _name, _src = suggest_fund(db, item.merchant, item.amount)
    item.suggested_fund_id = fund_id
    db.commit()
    db.refresh(item)
    return item
