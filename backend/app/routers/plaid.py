"""Plaid integration: link flow + transaction sync into the inbox."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Account, AccountType, PlaidInbox, PlaidItem
from ..services.suggest import suggest_fund

router = APIRouter(prefix="/plaid", tags=["plaid"])
log = logging.getLogger(__name__)


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


@router.post("/exchange")
def exchange_public_token(public_token: str, db: Session = Depends(get_db)):
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )

    resp = _client().item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    item = PlaidItem(item_id=resp["item_id"], access_token=resp["access_token"])
    db.add(item)
    db.commit()
    db.refresh(item)
    return {"item_id": item.item_id}


@router.post("/sync")
def sync_transactions(db: Session = Depends(get_db)):
    """Pull new Plaid transactions for all linked Items into the inbox."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    client = _client()
    items = db.scalars(select(PlaidItem)).all()
    if not items:
        raise HTTPException(400, "no Plaid items linked")

    total_added = 0
    for item in items:
        cursor = item.cursor or ""
        has_more = True
        while has_more:
            req = TransactionsSyncRequest(access_token=item.access_token, cursor=cursor)
            resp = client.transactions_sync(req)
            for t in resp["added"]:
                pid = t["transaction_id"]
                existing = db.scalar(
                    select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == pid)
                )
                if existing:
                    continue
                merchant = t.get("merchant_name") or t.get("name") or ""
                amount = t["amount"]
                txn_date = t["date"]
                acct = _ensure_account(db, t.get("account_id"))
                suggested_id, _n, _s = suggest_fund(db, merchant, amount)
                ib = PlaidInbox(
                    plaid_transaction_id=pid,
                    raw=t.to_dict() if hasattr(t, "to_dict") else dict(t),
                    merchant=merchant,
                    amount=amount,
                    date=txn_date,
                    account_id=acct.id if acct else None,
                    suggested_fund_id=suggested_id,
                )
                db.add(ib)
                total_added += 1
            cursor = resp["next_cursor"]
            has_more = resp["has_more"]
        item.cursor = cursor
    db.commit()
    return {"added": total_added}


def _ensure_account(db: Session, plaid_account_id: str | None):
    if not plaid_account_id:
        return None
    acct = db.scalar(select(Account).where(Account.plaid_account_id == plaid_account_id))
    if acct:
        return acct
    acct = Account(
        name=f"Plaid {plaid_account_id[:8]}",
        type=AccountType.checking,
        plaid_account_id=plaid_account_id,
        last_synced_at=datetime.now(timezone.utc),
    )
    db.add(acct)
    db.flush()
    return acct
