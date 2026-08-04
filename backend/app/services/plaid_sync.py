"""The Plaid sync: pull new transactions into the inbox, refresh balances.

This is not a route, and it used to live in one — which meant the nightly
scheduled job had to import out of the HTTP layer to find it. It lives here now,
and `run_sync` is the single description of what a sync does: the manual
`POST /plaid/sync` endpoint and the 06:00 job both call it, so they cannot drift.

Nothing here imports FastAPI or the Plaid SDK. The `PlaidClient` port arrives as
an argument, which is what lets the whole thing — floor dates, deduplication,
removed reconciliation, cursor advancement — be exercised from a stub.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import new_session
from ..models import Account, AccountType, PlaidInbox, PlaidItem
from .plaid_client import PlaidClient, build_plaid_client
from .suggest import suggest_fund

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkResult:
    """What linking produced, read off before the session forgets it — touching
    the ORM object after the commit would only send us back to the database."""

    item_id: str
    accounts_created: int


# Plaid account subtype → our AccountType (consulted first)
_SUBTYPE_MAP = {
    "checking": AccountType.checking,
    "savings": AccountType.savings,
    "credit card": AccountType.credit,
    "credit": AccountType.credit,
}

# Plaid parent type → our AccountType (fallback when subtype not in map)
_PARENT_TYPE_MAP = {
    "depository": AccountType.checking,
    "credit": AccountType.credit,
    "investment": AccountType.investment,
    # 'loan' and 'other' fall through to default checking
}


def classify_plaid_account(p: dict[str, Any]) -> AccountType:
    """Plaid returns parent `type` (depository/credit/investment/loan/other)
    AND a more granular `subtype`. Prefer subtype when it's something we
    recognize; otherwise use the parent type — that's how Roth/IRA/brokerage
    accounts land as `investment` regardless of their specific subtype."""
    subtype = str(p.get("subtype") or "").lower()
    if subtype in _SUBTYPE_MAP:
        return _SUBTYPE_MAP[subtype]
    parent = str(p.get("type") or "").lower()
    return _PARENT_TYPE_MAP.get(parent, AccountType.checking)


def link_item(
    db: Session,
    client: PlaidClient,
    public_token: str,
    institution_name: str | None = None,
) -> LinkResult:
    """Exchange a public token for an Item and persist it with its accounts.

    Both Plaid calls happen before anything is written, and the write is a
    single transaction. That ordering is the point: this used to commit the
    Item and only then fetch its accounts, so a failure in between stranded an
    Item with nothing under it — invisible in the UI and impossible to re-link,
    because Plaid had already spent the public token.

    Accounts are pulled now rather than left to the first sync so they appear
    immediately with real names and balances instead of placeholders.
    """
    linked = client.exchange_public_token(public_token)
    accounts = client.accounts(linked.access_token)

    item = PlaidItem(
        item_id=linked.item_id,
        access_token=linked.access_token,
        institution_name=institution_name,
    )
    db.add(item)
    db.flush()  # assigns item.id, which the account rows point at
    created = _upsert_accounts(db, item, accounts)
    db.commit()
    return LinkResult(item_id=linked.item_id, accounts_created=created)


def unlink_item(db: Session, item: PlaidItem) -> None:
    """Drop the Plaid link, keeping the accounts, their balances and history."""
    for a in db.scalars(select(Account).where(Account.plaid_item_id == item.id)).all():
        a.plaid_item_id = None
        a.plaid_account_id = None
    db.delete(item)
    db.commit()


def refresh_item_accounts(db: Session, client: PlaidClient, item: PlaidItem) -> int:
    """Fetch this Item's accounts from Plaid and upsert them. Returns the number
    of newly-created Account rows."""
    return _upsert_accounts(db, item, client.accounts(item.access_token))


def run_sync(db: Session, client: PlaidClient) -> int:
    """Pull new Plaid transactions and refresh balances. Returns count added.

    Transactions dated before `settings.plaid_sync_floor_date` are silently
    dropped — Plaid's /transactions/sync cursor is opaque and backfills up to
    24 months on first sync, so the floor keeps the inbox from drowning in
    history that's already accounted for in the seed.
    """
    items = db.scalars(select(PlaidItem)).all()
    if not items:
        return 0

    floor = _sync_floor()
    total_added = 0
    for item in items:
        # Refresh balances first so inbox account_id lookups land on fresh rows
        refresh_item_accounts(db, client, item)

        cursor = item.cursor or ""
        has_more = True
        while has_more:
            page = client.sync_transactions(item.access_token, cursor)
            for t in page.added:
                if _ingest(db, t, floor):
                    total_added += 1
            # Plaid emits `removed` for genuine reversals AND for the old id
            # when a pending transaction is replaced by its posted version.
            # Drop matching inbox rows so they don't linger as zombies.
            for r in page.removed:
                _reconcile_removed(db, r)
            cursor = page.next_cursor
            has_more = page.has_more
        item.cursor = cursor
    db.commit()
    return total_added


def run_daily_sync(client: PlaidClient | None = None) -> int:
    """The scheduled job end to end: own a session, build a client, log the result.

    The endpoint and the nightly job differ only in who supplies those two
    things — both land in `run_sync`, so a sync means the same thing either way.
    A failure is logged rather than raised: the scheduler has nowhere to put it,
    and the next night's run picks up from the cursor this one didn't advance.
    """
    db = new_session()
    try:
        added = run_sync(db, client or build_plaid_client())
        log.info("daily sync: added %d transactions", added)
        return added
    except Exception:
        log.exception("daily sync failed")
        return 0
    finally:
        db.close()


def _sync_floor() -> date | None:
    """The configured floor, or None if it's unreadable — a typo in the setting
    should let history through, not silently swallow every transaction."""
    try:
        return date.fromisoformat(settings.plaid_sync_floor_date)
    except ValueError:
        log.warning(
            "unreadable plaid_sync_floor_date %r — not filtering by date",
            settings.plaid_sync_floor_date,
        )
        return None


def _ingest(db: Session, t: dict[str, Any], floor: date | None) -> bool:
    """Add one Plaid transaction to the inbox. Returns whether it was added."""
    pid = t["transaction_id"]
    # Only ingest posted transactions. Pending rows would land with
    # pretip / pre-settlement amounts and then get replaced by a
    # new transaction_id once they post — which used to create
    # duplicates because pending and posted have different ids.
    if t.get("pending"):
        return False
    if db.scalar(select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == pid)):
        return False
    txn_date = t["date"]
    if floor and txn_date < floor:
        return False
    merchant = t.get("merchant_name") or t.get("name") or ""
    amount = t["amount"]
    acct = _account_for_plaid_id(db, t.get("account_id"))
    # Investment accounts: only the balance is tracked. Skip
    # transactions entirely — buys, sells, dividends, internal
    # transfers would flood the inbox with noise the user explicitly
    # doesn't want to categorize.
    if acct is not None and acct.type == AccountType.investment:
        return False
    suggested_id, _n, _s = suggest_fund(db, merchant, amount)
    db.add(
        PlaidInbox(
            plaid_transaction_id=pid,
            raw=_jsonable(t),
            merchant=merchant,
            amount=amount,
            date=txn_date,
            account_id=acct.id if acct else None,
            suggested_fund_id=suggested_id,
        )
    )
    return True


def _reconcile_removed(db: Session, removed: dict[str, Any]) -> None:
    rid = removed["transaction_id"]
    inbox_row = db.scalar(select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == rid))
    if inbox_row is not None:
        db.delete(inbox_row)


def _upsert_accounts(
    db: Session, item: PlaidItem, accounts: list[dict[str, Any]]
) -> int:
    """Write Plaid's view of this Item's accounts into our Account table.
    Returns the number of newly-created rows."""
    now = datetime.now(timezone.utc)
    created = 0
    for p in accounts:
        pid = p["account_id"]
        acct = db.scalar(select(Account).where(Account.plaid_account_id == pid))
        atype = classify_plaid_account(p)
        name = p.get("official_name") or p.get("name") or f"Plaid {pid[:8]}"
        balance = _balance_for(atype, p.get("balances") or {})
        if acct is None:
            acct = Account(
                name=name,
                type=atype,
                current_balance=balance,
                plaid_account_id=pid,
                plaid_item_id=item.id,
                last_synced_at=now,
            )
            db.add(acct)
            created += 1
        else:
            acct.current_balance = balance
            acct.last_synced_at = now
            if acct.plaid_item_id is None:
                acct.plaid_item_id = item.id
    db.flush()
    return created


def _balance_for(atype: AccountType, balances: dict[str, Any]) -> Decimal:
    """Checking/savings: prefer `available` — it nets out pending charges and
    unsettled deposits so the displayed balance matches what you can actually
    spend. Fall back to `current` if Plaid doesn't return it.

    Credit cards: `current` = amount owed, and we store it the same way
    (current_balance on a credit account = amount owed). Investments:
    `current` = market value."""
    if atype in (AccountType.checking, AccountType.savings):
        balance = balances.get("available")
        if balance is None:
            balance = balances.get("current") or 0
    else:
        balance = balances.get("current") or 0
    return Decimal(str(balance))


def _jsonable(obj):
    """Recursively coerce Plaid-returned dicts into JSON-serializable shape.
    Plaid SDK returns date/datetime/Decimal/Enum objects inside its model
    dicts; psycopg's JSONB encoder doesn't know how to serialize them."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    # Plaid enum objects have a .value attribute and survive json via str()
    if hasattr(obj, "value") and not isinstance(obj, (str, int, float, bool)):
        return str(obj)
    return obj


def _account_for_plaid_id(db: Session, plaid_account_id: str | None) -> Account | None:
    if not plaid_account_id:
        return None
    return db.scalar(select(Account).where(Account.plaid_account_id == plaid_account_id))
