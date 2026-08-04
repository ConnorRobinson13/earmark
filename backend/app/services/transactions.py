"""Transaction posting service.

Encapsulates the rules for each transaction type so that routers and importers
(Plaid inbox, manual quick-add) share the same logic.

Posting never computes an embedding. The row lands with `embedding` NULL and
`backfill_missing_embeddings` fills it in later, so a slow or unreachable Ollama
costs a backfill pass instead of up to ten seconds on every write — which used
to be paid once per row on the bulk import and Plaid sync loops.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import new_session
from ..models import Transaction, TxType
from .embeddings import INTERACTIVE_EMBED_TIMEOUT, embed_text_or_none

log = logging.getLogger(__name__)

# The backfill runs inside a request somebody is waiting on, so it is bounded by
# time rather than by completeness: whatever it doesn't reach, the next pass
# picks up. Checked between rows, so a single slow row can overshoot it by up to
# one `INTERACTIVE_EMBED_TIMEOUT`.
BACKFILL_BUDGET_SECONDS = 3.0

# Cap on rows pulled per pass. A bound on the query, not on the work — the
# budget above is what actually stops us.
_BACKFILL_BATCH = 500


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


def backfill_missing_embeddings(
    *, budget_seconds: float = BACKFILL_BUDGET_SECONDS
) -> int:
    """Embed transactions that were posted without one. Returns rows filled.

    Owns its session and commits it, rather than borrowing the caller's. The
    caller is `suggest_fund`, which serves read-only requests that never commit;
    work this expensive shouldn't be thrown away because of that, and it has no
    business riding along inside somebody else's transaction either.

    Newest first: a recent transaction is the likeliest useful neighbour, so if
    the budget runs out it should run out on the old rows.

    Stops at the first row the service can't answer for. When Ollama is down
    every row fails identically, and one refused connection is enough to know
    the rest of the pass is wasted.
    """
    started = time.monotonic()
    filled = 0
    db = new_session()
    try:
        pending = db.scalars(
            select(Transaction)
            .where(Transaction.embedding.is_(None), Transaction.merchant != "")
            .order_by(Transaction.id.desc())
            .limit(_BACKFILL_BATCH)
        ).all()
        for t in pending:
            if time.monotonic() - started >= budget_seconds:
                log.info(
                    "embedding backfill out of budget after %d rows, %d still pending",
                    filled,
                    len(pending) - filled,
                )
                break
            vec = embed_text_or_none(t.merchant, timeout=INTERACTIVE_EMBED_TIMEOUT)
            if vec is None:
                break
            t.embedding = vec
            filled += 1
        if filled:
            db.commit()
    finally:
        db.close()
    return filled


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
