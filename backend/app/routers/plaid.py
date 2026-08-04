"""Plaid HTTP surface: the link flow, linked items, and a manual sync trigger.

Routes only. The sync itself lives in `services.plaid_sync`, because it is not a
route and the nightly job needs it too. The Plaid client arrives by dependency
injection, so a test overrides `get_plaid_client` instead of the SDK.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, PlaidItem
from ..services import plaid_sync
from ..services.plaid_client import PlaidClient, PlaidNotConfigured, build_plaid_client

router = APIRouter(prefix="/plaid", tags=["plaid"])
log = logging.getLogger(__name__)


def get_plaid_client() -> PlaidClient:
    """One Plaid client per request. Missing credentials are a 400 here rather
    than an exception raised from the middle of a handler."""
    try:
        return build_plaid_client()
    except PlaidNotConfigured as e:
        raise HTTPException(400, str(e)) from e


@router.post("/link-token")
def create_link_token(client: PlaidClient = Depends(get_plaid_client)):
    return {"link_token": client.create_link_token()}


class ExchangeBody(BaseModel):
    public_token: str
    institution_name: str | None = None


@router.post("/exchange")
def exchange_public_token(
    body: ExchangeBody,
    db: Session = Depends(get_db),
    client: PlaidClient = Depends(get_plaid_client),
):
    result = plaid_sync.link_item(db, client, body.public_token, body.institution_name)
    return {"item_id": result.item_id, "accounts_created": result.accounts_created}


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


@router.post("/sync")
def sync_transactions(
    db: Session = Depends(get_db),
    client: PlaidClient = Depends(get_plaid_client),
):
    if not db.scalars(select(PlaidItem)).first():
        raise HTTPException(400, "no Plaid items linked")
    return {"added": plaid_sync.run_sync(db, client)}
