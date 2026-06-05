from datetime import date as _date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..db import get_db
from ..models import Transaction, TxType
from ..services import transactions as tx_svc

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[schemas.TransactionOut])
def list_transactions(
    fund_id: int | None = None,
    since: _date | None = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    q = select(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc())
    if fund_id is not None:
        q = q.where(Transaction.fund_id == fund_id)
    if since is not None:
        q = q.where(Transaction.date >= since)
    return db.scalars(q.limit(limit)).all()


@router.get("/search")
def search_transactions(
    start: _date | None = Query(None, description="inclusive start date"),
    end: _date | None = Query(None, description="inclusive end date"),
    merchant: str | None = Query(None, description="case-insensitive substring match"),
    fund_id: int | None = None,
    type: TxType | None = None,
    min_amount: float | None = Query(None, description="filter on absolute amount"),
    max_amount: float | None = Query(None, description="filter on absolute amount"),
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
):
    """Rich transaction search for analytical / conversational queries.

    Returns matching rows plus an aggregate summary (count, sum of signed
    amounts, sum of outflows, sum of inflows). Amounts are signed: negative =
    money out of a fund, positive = money in.
    """
    from sqlalchemy import func

    q = select(Transaction)
    if start is not None:
        q = q.where(Transaction.date >= start)
    if end is not None:
        q = q.where(Transaction.date <= end)
    if merchant:
        q = q.where(Transaction.merchant.ilike(f"%{merchant}%"))
    if fund_id is not None:
        q = q.where(Transaction.fund_id == fund_id)
    if type is not None:
        q = q.where(Transaction.type == type)
    if min_amount is not None:
        q = q.where(func.abs(Transaction.amount) >= min_amount)
    if max_amount is not None:
        q = q.where(func.abs(Transaction.amount) <= max_amount)

    rows = db.scalars(
        q.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit)
    ).all()

    signed = sum((r.amount for r in rows), start=Decimal("0"))
    outflow = sum((-r.amount for r in rows if r.amount < 0), start=Decimal("0"))
    inflow = sum((r.amount for r in rows if r.amount > 0), start=Decimal("0"))

    return {
        "count": len(rows),
        "summary": {
            "net": str(signed),
            "total_outflow": str(outflow),
            "total_inflow": str(inflow),
        },
        "transactions": [
            {
                "id": r.id,
                "date": r.date.isoformat(),
                "type": r.type.value,
                "amount": str(r.amount),
                "merchant": r.merchant,
                "notes": r.notes,
                "fund_id": r.fund_id,
            }
            for r in rows
        ],
    }


@router.post("/quick-add", response_model=schemas.TransactionOut, status_code=201)
def quick_add(body: schemas.QuickAddCreate, db: Session = Depends(get_db)):
    if body.type == TxType.expense:
        if body.fund_id is None:
            raise HTTPException(400, "expense requires fund_id")
        t = tx_svc.post_expense(
            db,
            fund_id=body.fund_id,
            amount=body.amount,
            txn_date=body.date,
            merchant=body.merchant,
            notes=body.notes,
        )
    elif body.type == TxType.income:
        t = tx_svc.post_income(
            db,
            fund_id=body.fund_id,
            amount=body.amount,
            txn_date=body.date,
            merchant=body.merchant,
            notes=body.notes,
        )
    else:
        raise HTTPException(400, "quick-add only supports expense or income")
    db.commit()
    db.refresh(t)
    return t


@router.post("/transfer", response_model=schemas.TransactionOut, status_code=201)
def transfer(body: schemas.TransferCreate, db: Session = Depends(get_db)):
    try:
        debit, credit = tx_svc.post_transfer(
            db,
            from_fund_id=body.from_fund_id,
            to_fund_id=body.to_fund_id,
            amount=body.amount,
            txn_date=body.date,
            notes=body.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    db.commit()
    db.refresh(credit)
    return credit


@router.post("/assign", response_model=schemas.TransactionOut, status_code=201)
def assign(body: schemas.AssignmentCreate, db: Session = Depends(get_db)):
    _debit, credit = tx_svc.post_assignment(
        db,
        fund_id=body.fund_id,
        amount=body.amount,
        txn_date=body.date,
        notes=body.notes,
    )
    db.commit()
    db.refresh(credit)
    return credit


@router.delete("/{txn_id}", status_code=204)
def delete_transaction(txn_id: int, db: Session = Depends(get_db)):
    t = db.get(Transaction, txn_id)
    if not t:
        raise HTTPException(404)
    # remove both sides of a linked transfer/assignment
    if t.linked_transaction_id:
        other = db.get(Transaction, t.linked_transaction_id)
        if other:
            db.delete(other)
    db.delete(t)
    db.commit()


@router.patch("/{txn_id}", response_model=schemas.TransactionOut)
def update_transaction(
    txn_id: int, body: schemas.TransactionBase, db: Session = Depends(get_db)
):
    t = db.get(Transaction, txn_id)
    if not t:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return t
