"""Keep goal balances in step with the accounts they're backed by.

When an account's `current_balance` is updated (manually now, via Plaid later),
every goal-fund backed by that account gets an adjusting income transaction so
its computed balance matches the account.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Fund, FundKind
from . import transactions as tx_svc
from .balances import fund_balance


def sync_goals_for_account(db: Session, account_id: int) -> int:
    """Sync all goals backed by this account to its current_balance. Returns count adjusted."""
    acct = db.get(Account, account_id)
    if not acct:
        return 0
    target = Decimal(acct.current_balance)
    goals = db.scalars(
        select(Fund).where(
            Fund.backed_by_account_id == account_id,
            Fund.kind == FundKind.goal,
            Fund.archived_at.is_(None),
        )
    ).all()
    adjusted = 0
    for g in goals:
        current = fund_balance(db, g.id)
        delta = target - current
        if delta == 0:
            continue
        tx_svc.post_income_signed(
            db,
            fund_id=g.id,
            amount=delta,
            txn_date=date.today(),
            merchant=f"Auto-sync from {acct.name}",
        )
        adjusted += 1
    return adjusted
