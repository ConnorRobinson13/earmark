from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Account
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
    account_id: int, body: schemas.AccountBase, db: Session = Depends(get_db)
):
    a = db.get(Account, account_id)
    if not a:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    balance_changed = "current_balance" in data
    for k, v in data.items():
        setattr(a, k, v)
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
    db.delete(a)
    db.commit()
