from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Fund, FundKind, GoalSettlement, InboxStatus, PlaidInbox
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
    # Plaid signs purchases positive; treat any positive amount as expense, negative as income.
    is_income = item.amount < 0

    # Income + as_paycheck → land in Unassigned (fund_id=NULL). Informational
    # under the planned-income model; does NOT bump Unassigned because Unassigned
    # is computed from planned_income minus assignments, not from received cash.
    if is_income and body.as_paycheck:
        fund_id = None
    else:
        fund_id = body.fund_id or item.suggested_fund_id
        if fund_id is None:
            raise HTTPException(400, "no fund chosen and no suggestion available")

    # The same Plaid transaction can reach a pending inbox row twice: a `removed`
    # page deletes the row it was approved from and leaves the posted ledger
    # entry behind, so a later page re-adds the id with nothing in the inbox to
    # dedupe against. Posting it again trips the unique index on
    # `transactions.plaid_transaction_id` — which is how approving turned into a
    # 500. Adopt the entry that is already there instead: approving means one
    # ledger row for this Plaid id, tagged to the fund just chosen. No goal
    # settlement is recorded on this path; the approve that posted the row
    # recorded it already, and a second one would double the contribution.
    already_posted = tx_svc.find_by_plaid_id(db, item.plaid_transaction_id)
    if already_posted is not None:
        already_posted.fund_id = fund_id
        _mark_reviewed(item)
        db.commit()
        db.refresh(already_posted)
        return already_posted

    if is_income:
        t = tx_svc.post_income(
            db,
            fund_id=fund_id,
            amount=-item.amount,
            txn_date=item.date,
            merchant=item.merchant,
            plaid_transaction_id=item.plaid_transaction_id,
        )
    else:
        t = tx_svc.post_expense(
            db,
            fund_id=fund_id,
            amount=item.amount,
            txn_date=item.date,
            merchant=item.merchant,
            plaid_transaction_id=item.plaid_transaction_id,
        )

    # Auto-settle: if this is an income approved into a goal fund, that's a
    # physical contribution arriving. Record it as a GoalSettlement too so the
    # To-Move panel's pending tally clears and contribution_ytd / saved_this_month
    # reflect it — without the user clicking "Mark moved" separately.
    if is_income and fund_id is not None:
        fund = db.get(Fund, fund_id)
        if fund and fund.kind == FundKind.goal:
            db.add(GoalSettlement(
                goal_id=fund.id,
                from_account_id=None,  # unknown — Plaid only shows the destination side
                to_account_id=fund.backed_by_account_id,
                amount=-item.amount,
                settled_at=item.date,
            ))

    _mark_reviewed(item)
    db.commit()
    db.refresh(t)
    return t


def _mark_reviewed(item: PlaidInbox) -> None:
    item.status = InboxStatus.approved
    item.reviewed_at = datetime.now(timezone.utc)


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
