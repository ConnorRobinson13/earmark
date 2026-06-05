"""Plaid integration: link flow + transaction sync into the inbox."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Account, AccountType, PlaidInbox, PlaidItem
from ..services.suggest import suggest_fund

router = APIRouter(prefix="/plaid", tags=["plaid"])
log = logging.getLogger(__name__)


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


def _classify_plaid_account(p) -> AccountType:
    """Plaid returns parent `type` (depository/credit/investment/loan/other)
    AND a more granular `subtype`. Prefer subtype when it's something we
    recognize; otherwise use the parent type — that's how Roth/IRA/brokerage
    accounts land as `investment` regardless of their specific subtype."""
    subtype = str(p.get("subtype") or "").lower()
    if subtype in _SUBTYPE_MAP:
        return _SUBTYPE_MAP[subtype]
    parent = str(p.get("type") or "").lower()
    return _PARENT_TYPE_MAP.get(parent, AccountType.checking)


def _client():
    if not settings.plaid_client_id or not settings.plaid_secret:
        raise HTTPException(400, "Plaid credentials not configured")
    from plaid import Configuration, ApiClient, Environment
    from plaid.api import plaid_api

    env_map = {
        "sandbox": Environment.Sandbox,
        "production": Environment.Production,
    }
    cfg = Configuration(
        host=env_map.get(settings.plaid_env, Environment.Sandbox),
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(ApiClient(cfg))


@router.post("/link-token")
def create_link_token():
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.country_code import CountryCode
    from plaid.model.products import Products

    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id="budget-app-local"),
        client_name="Budget App",
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
    )
    resp = _client().link_token_create(req)
    return {"link_token": resp["link_token"]}


class ExchangeBody(BaseModel):
    public_token: str
    institution_name: str | None = None


@router.post("/exchange")
def exchange_public_token(body: ExchangeBody, db: Session = Depends(get_db)):
    """Exchange the public_token, store the Item, then pull its accounts so
    they show up immediately (with real names + balances) instead of waiting
    for first sync to auto-create placeholders.
    """
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )

    client = _client()
    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=body.public_token)
    )
    item = PlaidItem(
        item_id=resp["item_id"],
        access_token=resp["access_token"],
        institution_name=body.institution_name,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    created = _refresh_item_accounts(db, client, item)
    db.commit()
    return {"item_id": item.item_id, "accounts_created": created}


@router.get("/items")
def list_items(db: Session = Depends(get_db)):
    """List linked Plaid items + their accounts."""
    items = db.scalars(select(PlaidItem)).all()
    out = []
    for it in items:
        accts = db.scalars(
            select(Account).where(Account.plaid_item_id == it.id)
        ).all()
        out.append({
            "id": it.id,
            "item_id": it.item_id,
            "institution_name": it.institution_name,
            "accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "type": a.type.value,
                    "current_balance": str(a.current_balance),
                    "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
                }
                for a in accts
            ],
        })
    return out


@router.delete("/items/{item_id}", status_code=204)
def unlink_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(PlaidItem, item_id)
    if not item:
        raise HTTPException(404)
    # Detach accounts (keep balances + history, just drop the Plaid link)
    for a in db.scalars(select(Account).where(Account.plaid_item_id == item.id)).all():
        a.plaid_item_id = None
        a.plaid_account_id = None
    db.delete(item)
    db.commit()


def run_sync(db: Session) -> int:
    """Pull new Plaid transactions and refresh balances. Returns count added.
    Safe to call from the HTTP endpoint OR the scheduled daily job.

    Transactions dated before `settings.plaid_sync_floor_date` are silently
    dropped — Plaid's /transactions/sync cursor is opaque and backfills up to
    24 months on first sync, so the floor keeps the inbox from drowning in
    history that's already accounted for in the seed.
    """
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    client = _client()
    items = db.scalars(select(PlaidItem)).all()
    if not items:
        return 0

    try:
        floor = date.fromisoformat(settings.plaid_sync_floor_date)
    except ValueError:
        floor = None

    total_added = 0
    for item in items:
        # Refresh balances first so inbox account_id lookups land on fresh rows
        _refresh_item_accounts(db, client, item)

        cursor = item.cursor or ""
        has_more = True
        while has_more:
            req = TransactionsSyncRequest(access_token=item.access_token, cursor=cursor)
            resp = client.transactions_sync(req)
            for t in resp["added"]:
                pid = t["transaction_id"]
                # Only ingest posted transactions. Pending rows would land with
                # pretip / pre-settlement amounts and then get replaced by a
                # new transaction_id once they post — which used to create
                # duplicates because pending and posted have different ids.
                if t.get("pending"):
                    continue
                if db.scalar(select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == pid)):
                    continue
                txn_date = t["date"]
                if floor and txn_date < floor:
                    continue
                merchant = t.get("merchant_name") or t.get("name") or ""
                amount = t["amount"]
                acct = _account_for_plaid_id(db, t.get("account_id"))
                # Investment accounts: only the balance is tracked. Skip
                # transactions entirely — buys, sells, dividends, internal
                # transfers would flood the inbox with noise the user explicitly
                # doesn't want to categorize.
                if acct is not None and acct.type == AccountType.investment:
                    continue
                suggested_id, _n, _s = suggest_fund(db, merchant, amount)
                ib = PlaidInbox(
                    plaid_transaction_id=pid,
                    raw=_jsonable(t.to_dict() if hasattr(t, "to_dict") else dict(t)),
                    merchant=merchant,
                    amount=amount,
                    date=txn_date,
                    account_id=acct.id if acct else None,
                    suggested_fund_id=suggested_id,
                )
                db.add(ib)
                total_added += 1
            # Plaid emits `removed` for genuine reversals AND for the old id
            # when a pending transaction is replaced by its posted version.
            # Drop matching inbox rows so they don't linger as zombies.
            for r in resp.get("removed", []):
                rid = r.get("transaction_id") if isinstance(r, dict) else r["transaction_id"]
                inbox_row = db.scalar(select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == rid))
                if inbox_row is not None:
                    db.delete(inbox_row)
            cursor = resp["next_cursor"]
            has_more = resp["has_more"]
        item.cursor = cursor
    db.commit()
    return total_added


@router.post("/sync")
def sync_transactions(db: Session = Depends(get_db)):
    if not db.scalars(select(PlaidItem)).first():
        raise HTTPException(400, "no Plaid items linked")
    return {"added": run_sync(db)}


def _refresh_item_accounts(db: Session, client, item: PlaidItem) -> int:
    """Fetch this Item's accounts from Plaid and upsert into our Account table.
    Returns number of newly-created Account rows."""
    from plaid.model.accounts_get_request import AccountsGetRequest

    resp = client.accounts_get(AccountsGetRequest(access_token=item.access_token))
    now = datetime.now(timezone.utc)
    created = 0
    for p in resp["accounts"]:
        pid = p["account_id"]
        acct = db.scalar(select(Account).where(Account.plaid_account_id == pid))
        atype = _classify_plaid_account(p)
        balances = p.get("balances", {})
        # Checking/savings: prefer `available` — it nets out pending charges and
        # unsettled deposits so the displayed balance matches what you can
        # actually spend. Fall back to `current` if Plaid doesn't return it.
        # Credit cards: `current` = amount owed. Investments: `current` = market value.
        if atype in (AccountType.checking, AccountType.savings):
            balance = balances.get("available")
            if balance is None:
                balance = balances.get("current") or 0
        else:
            balance = balances.get("current") or 0
        # For credit cards Plaid reports the balance as positive owed amount.
        # We store it the same way (current_balance on a credit account = amount owed).
        name = p.get("official_name") or p.get("name") or f"Plaid {pid[:8]}"
        if acct is None:
            acct = Account(
                name=name,
                type=atype,
                current_balance=Decimal(str(balance)),
                plaid_account_id=pid,
                plaid_item_id=item.id,
                last_synced_at=now,
            )
            db.add(acct)
            created += 1
        else:
            acct.current_balance = Decimal(str(balance))
            acct.last_synced_at = now
            if acct.plaid_item_id is None:
                acct.plaid_item_id = item.id
    db.flush()
    return created


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


def _account_for_plaid_id(db: Session, plaid_account_id: str | None):
    if not plaid_account_id:
        return None
    return db.scalar(select(Account).where(Account.plaid_account_id == plaid_account_id))
