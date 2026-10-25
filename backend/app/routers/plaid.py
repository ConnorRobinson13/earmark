"""Plaid HTTP surface: the link flow, linked items, and a manual sync trigger.

Routes only. The sync itself lives in `services.plaid_sync`, because it is not a
route and the nightly job needs it too. The Plaid client arrives by dependency
injection, so a test overrides `get_plaid_client` instead of the SDK.
"""
from __future__ import annotations

import logging
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, PlaidItem
from ..services import plaid_sync
from ..services.plaid_client import (
    PlaidApiError,
    PlaidClient,
    PlaidNotConfigured,
    build_plaid_client,
)

router = APIRouter(prefix="/plaid", tags=["plaid"])
log = logging.getLogger(__name__)
_ITEM_STATUS_CACHE_TTL_SECONDS = 30.0
_ITEM_STATUS_FAILURE_CACHE_TTL_SECONDS = 5.0
_PERSISTENT_ITEM_ERROR_CODES = {
    "ITEM_LOGIN_REQUIRED",
    "ITEM_NOT_FOUND",
    "INVALID_ACCESS_TOKEN",
}
_UPDATE_MODE_UNSUPPORTED_CODES = {"ITEM_NOT_FOUND", "INVALID_ACCESS_TOKEN"}
_item_status_cache: dict[int, tuple[float, str | None, bool]] = {}
_item_status_cache_lock = Lock()


def get_optional_plaid_client() -> PlaidClient | None:
    """Build a Plaid client when credentials exist; status reads are best-effort."""
    try:
        return build_plaid_client()
    except PlaidNotConfigured:
        return None


def get_plaid_client() -> PlaidClient:
    """One configured Plaid client per request."""
    client = get_optional_plaid_client()
    if client is None:
        raise HTTPException(
            400,
            detail={
                "code": "PLAID_CREDENTIALS_NOT_CONFIGURED",
                "message": "Plaid credentials not configured",
            },
        )
    return client


def clear_item_status_cache(item_id: int | None = None) -> None:
    """Invalidate cached Item statuses after a sync or unlink operation."""
    with _item_status_cache_lock:
        if item_id is None:
            _item_status_cache.clear()
        else:
            _item_status_cache.pop(item_id, None)


def _cached_item_status(
    client: PlaidClient, item: PlaidItem
) -> tuple[str | None, bool]:
    now = monotonic()
    with _item_status_cache_lock:
        cached = _item_status_cache.get(item.id)
        if cached:
            ttl = (
                _ITEM_STATUS_CACHE_TTL_SECONDS
                if cached[2]
                else _ITEM_STATUS_FAILURE_CACHE_TTL_SECONDS
            )
            if now - cached[0] < ttl:
                return cached[1], cached[2]

    error_code = None
    status_available = True
    try:
        error_code = client.item_error_code(item.access_token)
    except PlaidApiError as exc:
        log.warning(
            "Plaid Item status lookup failed for %s (HTTP %s, provider code %s, request_id %s)",
            item.institution_name or "Unnamed institution",
            exc.status,
            exc.error_code,
            exc.request_id,
        )
        if exc.error_code in _PERSISTENT_ITEM_ERROR_CODES:
            error_code = exc.error_code
        else:
            status_available = False
    except Exception as exc:
        log.error(
            "Unexpected Plaid Item status lookup failure for %s (%s); status is unavailable",
            item.institution_name or "Unnamed institution",
            type(exc).__name__,
        )
        status_available = False

    with _item_status_cache_lock:
        _item_status_cache[item.id] = (monotonic(), error_code, status_available)
    return error_code, status_available


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
def list_items(
    db: Session = Depends(get_db),
    client: PlaidClient | None = Depends(get_optional_plaid_client),
):
    """List linked Plaid items + accounts and best-effort current Item status."""
    items = db.scalars(select(PlaidItem)).all()
    out = []
    for it in items:
        accts = db.scalars(
            select(Account).where(Account.plaid_item_id == it.id)
        ).all()
        error_code = None
        status_available = None
        if client is not None:
            error_code, status_available = _cached_item_status(client, it)
        out.append({
            "id": it.id,
            "item_id": it.item_id,
            "institution_name": it.institution_name,
            "error_code": error_code,
            "needs_reauthentication": error_code == "ITEM_LOGIN_REQUIRED",
            "status_available": status_available,
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


@router.post("/items/{item_id}/update-link-token")
def create_update_link_token(
    item_id: int,
    db: Session = Depends(get_db),
    client: PlaidClient = Depends(get_plaid_client),
):
    """Create a Plaid Link update-mode token without exposing the access token."""
    item = db.get(PlaidItem, item_id)
    if item is None:
        raise HTTPException(404, "Plaid item not found")
    try:
        return {"link_token": client.create_update_link_token(item.access_token)}
    except PlaidApiError as exc:
        log.warning(
            "Plaid update-link token failed for %s (HTTP %s, provider code %s, request_id %s)",
            item.institution_name or "Unnamed institution",
            exc.status,
            exc.error_code,
            exc.request_id,
        )
        message = (
            "Plaid no longer recognizes this linked Item; update mode cannot repair it."
            if exc.error_code in _UPDATE_MODE_UNSUPPORTED_CODES
            else "Plaid could not start the reauthentication session. Try again later."
        )
        raise HTTPException(
            502,
            detail={
                "code": "PLAID_UPDATE_LINK_FAILED",
                "error_code": exc.error_code,
                "message": message,
            },
        ) from exc


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
    clear_item_status_cache(item_id)


@router.post("/sync")
def sync_transactions(
    db: Session = Depends(get_db),
    client: PlaidClient = Depends(get_plaid_client),
):
    if not db.scalars(select(PlaidItem)).first():
        raise HTTPException(400, "no Plaid items linked")
    result = plaid_sync.run_sync(db, client)
    clear_item_status_cache()
    return {"added": result.added, "issues": [issue.as_dict() for issue in result.issues]}
