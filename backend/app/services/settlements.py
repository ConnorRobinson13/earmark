"""Settling a goal contribution, and undoing one, as a single reversible move.

Marking a goal "moved" shifts real cash from a source account into the goal's
backing account; undoing it shifts the same cash back. Written as two handlers
those are mirror images kept in step by hand, and nothing stops one side from
drifting when the other changes.

So the money movement is described once, as signed per-account deltas, and the
undo applies that same description negated. There is only one place where the
arithmetic lives, and the inverse is derived from it rather than retyped.

Callers own the transaction: these functions flush so ids are visible, but
never commit.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ..models import Account, Fund, GoalSettlement

# Signed balance deltas to apply, keyed by account id.
AccountDeltas = dict[int, Decimal]


def settle_goal(
    db: Session,
    *,
    goal: Fund,
    amount: Decimal,
    settled_at: date,
    from_account_id: int | None = None,
) -> GoalSettlement:
    """Record that `amount` moved from `from_account_id` into the goal's backing
    account, and move both balances to match.

    The goal's own fund balance is deliberately untouched — the assignment that
    earmarked this money already credited it earlier in the month.

    An account id that names nothing is recorded as no account at all, which is
    also how a settlement with no source (or a goal with no backing account) is
    stored: that side simply doesn't move.
    """
    if amount <= 0:
        raise ValueError("amount must be positive")

    from_acct = db.get(Account, from_account_id) if from_account_id else None
    to_acct = db.get(Account, goal.backed_by_account_id) if goal.backed_by_account_id else None

    settlement = GoalSettlement(
        goal_id=goal.id,
        from_account_id=from_acct.id if from_acct else None,
        to_account_id=to_acct.id if to_acct else None,
        amount=amount,
        settled_at=settled_at,
    )
    # Move balances from the *stored* row, not from `amount` as it was handed in:
    # the column is Numeric(12, 2), so a sub-cent amount is rounded on the way in,
    # and the rounded value is what a later undo reads back. Settling on anything
    # else would leave a residue behind that the undo can't reverse.
    db.add(settlement)
    db.flush()
    db.refresh(settlement)
    _apply(db, _movement(settlement))
    return settlement


def unsettle(db: Session, settlement: GoalSettlement) -> None:
    """Undo `settlement` — the exact reverse of the balance movement settling
    made — and drop the record. Whatever `settle_goal` does to an account, this
    puts back, because both read the same movement."""
    _apply(db, _inverse(_movement(settlement)))
    db.delete(settlement)
    db.flush()


def _movement(settlement: GoalSettlement) -> AccountDeltas:
    """The balance deltas a settlement stands for: the source loses the amount,
    the destination gains it.

    Deltas accumulate per account, so a goal backed by the very account the cash
    came from nets to zero rather than being debited and credited in sequence.
    """
    amount = Decimal(settlement.amount)
    sides = ((settlement.from_account_id, -amount), (settlement.to_account_id, amount))
    deltas: AccountDeltas = {}
    for account_id, delta in sides:
        if account_id is None:  # no source named, or a goal with no backing account
            continue
        deltas[account_id] = deltas.get(account_id, Decimal(0)) + delta
    return deltas


def _inverse(deltas: AccountDeltas) -> AccountDeltas:
    """The movement that cancels `deltas`."""
    return {account_id: -delta for account_id, delta in deltas.items()}


def _apply(db: Session, deltas: AccountDeltas) -> None:
    """Add each delta to the account's live balance.

    A delta naming no live account is skipped rather than raising: settlement
    rows outlive the accounts they reference (deleting an account nulls the
    link), so an undo has to move whatever accounts are still there and let the
    rest go.
    """
    for account_id, delta in deltas.items():
        acct = db.get(Account, account_id)
        if acct is None:
            continue
        acct.current_balance = Decimal(acct.current_balance) + delta
