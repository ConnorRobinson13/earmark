"""Transaction posting service.

Encapsulates the rules for each transaction type so that routers and importers
(Plaid inbox, manual quick-add) share the same logic.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Transaction, TxType
from .embeddings import embed_text_or_none


def _post(
    db: Session,
    *,
    fund_id: Optional[int],
    type_: TxType,
    amount: Decimal,
    txn_date: date,
    merchant: str = "",
    notes: Optional[str] = None,
    plaid_transaction_id: Optional[str] = None,
    linked_transaction_id: Optional[int] = None,
    embedding: Optional[list[float]] = None,
) -> Transaction:
    t = Transaction(
        fund_id=fund_id,
        type=type_,
        amount=amount,
        date=txn_date,
        merchant=merchant,
        notes=notes,
        plaid_transaction_id=plaid_transaction_id,
        linked_transaction_id=linked_transaction_id,
        embedding=embedding,
    )
    db.add(t)
    db.flush()
    return t


def post_expense(
    db: Session,
    *,
    fund_id: int,
    amount: Decimal,
    txn_date: date,
    merchant: str = "",
    notes: Optional[str] = None,
    plaid_transaction_id: Optional[str] = None,
) -> Transaction:
    """Amount is positive from the caller; stored as negative on the fund."""
    embedding = embed_text_or_none(merchant)
    return _post(
        db,
        fund_id=fund_id,
        type_=TxType.expense,
        amount=-abs(amount),
        txn_date=txn_date,
        merchant=merchant,
        notes=notes,
        plaid_transaction_id=plaid_transaction_id,
        embedding=embedding,
    )


def post_income(
    db: Session,
    *,
    fund_id: Optional[int],
    amount: Decimal,
    txn_date: date,
    merchant: str = "",
    notes: Optional[str] = None,
    plaid_transaction_id: Optional[str] = None,
) -> Transaction:
    """If fund_id is None, lands in Unassigned. Otherwise tagged directly."""
    embedding = embed_text_or_none(merchant)
    return _post(
        db,
        fund_id=fund_id,
        type_=TxType.income,
        amount=abs(amount),
        txn_date=txn_date,
        merchant=merchant,
        notes=notes,
        plaid_transaction_id=plaid_transaction_id,
        embedding=embedding,
    )


def post_income_signed(
    db: Session,
    *,
    fund_id: Optional[int],
    amount: Decimal,
    txn_date: date,
    merchant: str = "",
    notes: Optional[str] = None,
) -> Optional[Transaction]:
    """Signed-amount income for adjustments (negative allowed). Returns None for zero."""
    if amount == 0:
        return None
    return _post(
        db,
        fund_id=fund_id,
        type_=TxType.income,
        amount=amount,
        txn_date=txn_date,
        merchant=merchant,
        notes=notes,
        embedding=embed_text_or_none(merchant),
    )


def post_transfer(
    db: Session,
    *,
    from_fund_id: int,
    to_fund_id: int,
    amount: Decimal,
    txn_date: date,
    notes: Optional[str] = None,
) -> tuple[Transaction, Transaction]:
    if from_fund_id == to_fund_id:
        raise ValueError("Cannot transfer to the same fund")
    amt = abs(amount)
    debit = _post(
        db,
        fund_id=from_fund_id,
        type_=TxType.transfer,
        amount=-amt,
        txn_date=txn_date,
        notes=notes,
    )
    credit = _post(
        db,
        fund_id=to_fund_id,
        type_=TxType.transfer,
        amount=amt,
        txn_date=txn_date,
        notes=notes,
        linked_transaction_id=debit.id,
    )
    debit.linked_transaction_id = credit.id
    db.flush()
    return debit, credit


def post_assignment(
    db: Session,
    *,
    fund_id: int,
    amount: Decimal,
    txn_date: date,
    notes: Optional[str] = None,
) -> tuple[Transaction, Transaction]:
    """Move money between Unassigned (fund_id=NULL) and a fund.

    Positive amount: Unassigned -> fund. Negative: fund -> Unassigned.
    """
    if amount == 0:
        raise ValueError("assignment amount must be non-zero")
    # unassigned side gets -amount, fund side gets +amount
    unassigned_entry = _post(
        db,
        fund_id=None,
        type_=TxType.assignment,
        amount=-amount,
        txn_date=txn_date,
        notes=notes,
    )
    fund_entry = _post(
        db,
        fund_id=fund_id,
        type_=TxType.assignment,
        amount=amount,
        txn_date=txn_date,
        notes=notes,
        linked_transaction_id=unassigned_entry.id,
    )
    unassigned_entry.linked_transaction_id = fund_entry.id
    db.flush()
    return unassigned_entry, fund_entry
