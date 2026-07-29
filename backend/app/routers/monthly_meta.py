"""Per-month planning numbers (planned_income today, maybe more later)."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MonthlyMeta
from ..month import parse_month

router = APIRouter(prefix="/monthly-meta", tags=["monthly-meta"])


class MonthlyMetaOut(BaseModel):
    month: date
    planned_income: Decimal


class MonthlyMetaPatch(BaseModel):
    planned_income: Decimal


@router.get("/{month}", response_model=MonthlyMetaOut)
def get_meta(month: str, db: Session = Depends(get_db)):
    first = parse_month(month)
    row = db.get(MonthlyMeta, first)
    if row is None:
        return MonthlyMetaOut(month=first, planned_income=Decimal("0"))
    return MonthlyMetaOut(month=row.month, planned_income=row.planned_income)


@router.put("/{month}", response_model=MonthlyMetaOut)
def upsert_meta(month: str, body: MonthlyMetaPatch, db: Session = Depends(get_db)):
    first = parse_month(month)
    row = db.get(MonthlyMeta, first)
    if row is None:
        row = MonthlyMeta(month=first, planned_income=body.planned_income)
        db.add(row)
    else:
        row.planned_income = body.planned_income
    db.commit()
    db.refresh(row)
    return MonthlyMetaOut(month=row.month, planned_income=row.planned_income)


@router.get("", response_model=list[MonthlyMetaOut])
def list_meta(db: Session = Depends(get_db)):
    rows = db.scalars(select(MonthlyMeta).order_by(MonthlyMeta.month)).all()
    return [MonthlyMetaOut(month=r.month, planned_income=r.planned_income) for r in rows]
