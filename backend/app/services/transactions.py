"""Transaction posting service.

Encapsulates the rules for each transaction type so that routers and importers
(Plaid inbox, manual quick-add) share the same logic.

Posting never computes an embedding. The row lands with `embedding` NULL and
`embeddings.backfill_missing_embeddings` fills it in later, so a slow or
unreachable Ollama costs a backfill pass instead of up to ten seconds on every
write — which used to be paid once per row on the bulk import and Plaid sync
loops. Nothing in here reaches for the embedding client any more.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Fund, Transaction, TxType


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
    return _post(
        db,
        fund_id=fund_id,
        type_=TxType.expense,
        amount=-abs(amount),
        txn_date=txn_date,
        merchant=merchant,
        notes=notes,
        plaid_transaction_id=plaid_transaction_id,
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
    return _post(
        db,
        fund_id=fund_id,
        type_=TxType.income,
        amount=abs(amount),
        txn_date=txn_date,
        merchant=merchant,
        notes=notes,
        plaid_transaction_id=plaid_transaction_id,
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


def move_transaction(
    db: Session,
    *,
    txn_id: int,
    fund_id: int,
) -> Transaction:
    """Re-tag an already-assigned transaction to a different fund.

    Only `fund_id` changes: the amount, date, merchant, notes and Plaid id ride
    along on the same row, so the transaction keeps its identity and no second
    row is created. The old fund loses the amount and the new fund gains it, and
    because every balance is the signed sum of a fund's rows (see
    `balances.fund_balance`) both sides re-derive on the next read — nothing to
    recompute here.

    Guards the move rather than trusting the caller: a missing transaction is a
    `LookupError` (→ 404) and every rejected destination is a `ValueError`
    (→ 400) raised *before* anything is written, so a bad move leaves the row
    untouched. Transfers and assignments are double-entry pairs whose two legs
    must stay balanced, so a single-sided move of one is refused; this action is
    for the ordinary expense/income rows the inbox and quick-add produce.
    """
    t = db.get(Transaction, txn_id)
    if t is None:
        raise LookupError("transaction not found")
    if t.fund_id is None:
        raise ValueError("transaction is not assigned to a fund")
    if t.type in (TxType.transfer, TxType.assignment) or t.linked_transaction_id is not None:
        raise ValueError("cannot move a transfer or assignment leg between funds")

    dest = db.get(Fund, fund_id)
    if dest is None or dest.archived_at is not None:
        raise ValueError("destination fund does not exist or is archived")
    if dest.id == t.fund_id:
        raise ValueError("transaction is already in that fund")

    t.fund_id = dest.id
    db.flush()
    return t


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
