"""Payday schedule CRUD — recurring deposits that drive the cash-flow projection."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import PaydaySchedule

router = APIRouter(prefix="/paydays", tags=["paydays"])


@router.get("", response_model=list[schemas.PaydayOut])
def list_paydays(db: Session = Depends(get_db)):
    return db.scalars(
        select(PaydaySchedule).order_by(PaydaySchedule.day_of_month, PaydaySchedule.id)
    ).all()


@router.post("", response_model=schemas.PaydayOut, status_code=201)
def create_payday(body: schemas.PaydayCreate, db: Session = Depends(get_db)):
    p = PaydaySchedule(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{payday_id}")
def delete_payday(payday_id: int, db: Session = Depends(get_db)):
    p = db.get(PaydaySchedule, payday_id)
    if not p:
        raise HTTPException(404)
    db.delete(p)
    db.commit()
    return {"deleted": True}
