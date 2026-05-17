from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import MonthlyTemplate
from ..services import transactions as tx_svc

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[schemas.TemplateItem])
def list_templates(db: Session = Depends(get_db)):
    return db.scalars(select(MonthlyTemplate).order_by(MonthlyTemplate.id)).all()


@router.put("", response_model=list[schemas.TemplateItem])
def replace_templates(items: list[schemas.TemplateItem], db: Session = Depends(get_db)):
    """Replace the entire template set in one call."""
    db.query(MonthlyTemplate).delete()
    db.flush()
    for it in items:
        db.add(MonthlyTemplate(fund_id=it.fund_id, planned_amount=it.planned_amount))
    db.commit()
    return db.scalars(select(MonthlyTemplate).order_by(MonthlyTemplate.id)).all()


@router.post("/apply")
def apply_template(body: schemas.TemplateApply, db: Session = Depends(get_db)):
    """Apply each template line as an assignment dated to the 1st of the target month."""
    items = db.scalars(select(MonthlyTemplate)).all()
    if not items:
        raise HTTPException(400, "no template configured")
    target = body.month.replace(day=1)
    applied = 0
    for it in items:
        tx_svc.post_assignment(
            db,
            fund_id=it.fund_id,
            amount=it.planned_amount,
            txn_date=target,
            notes=f"Auto-applied from template for {target.isoformat()}",
        )
        applied += 1
    db.commit()
    return {"applied": applied, "month": target.isoformat()}
