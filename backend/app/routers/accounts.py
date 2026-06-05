from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from sqlalchemy import update

from ..models import Account, Fund, GoalSettlement, PlaidInbox
from ..services.account_sync import sync_goals_for_account

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("", response_model=list[schemas.AccountOut])
def list_accounts(db: Session = Depends(get_db)):
    return db.scalars(select(Account).order_by(Account.id)).all()


@router.post("", response_model=schemas.AccountOut, status_code=201)
def create_account(body: schemas.AccountCreate, db: Session = Depends(get_db)):
    a = Account(**body.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.patch("/{account_id}", response_model=schemas.AccountOut)
def update_account(
    account_id: int, body: schemas.AccountUpdate, db: Session = Depends(get_db)
):
    from datetime import datetime, timezone
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    balance_changed = "current_balance" in data
    for k, v in data.items():
        setattr(a, k, v)
    if balance_changed:
        # Manual edit counts as a sync — stamp it so the UI can show freshness
        a.last_synced_at = datetime.now(timezone.utc)
    db.flush()
    if balance_changed:
        sync_goals_for_account(db, a.id)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, db: Session = Depends(get_db)):
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404)
    # Detach any FKs pointing at this account first — goals stay, settlement
    # history stays, the link just drops.
    db.execute(
        update(Fund).where(Fund.backed_by_account_id == a.id).values(backed_by_account_id=None)
    )
    db.execute(
        update(GoalSettlement)
        .where(GoalSettlement.from_account_id == a.id)
        .values(from_account_id=None)
    )
    db.execute(
        update(GoalSettlement)
        .where(GoalSettlement.to_account_id == a.id)
        .values(to_account_id=None)
    )
    db.execute(
        update(PlaidInbox).where(PlaidInbox.account_id == a.id).values(account_id=None)
    )
    db.flush()
    db.delete(a)
    db.commit()
