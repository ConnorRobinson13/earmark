"""AI-assisted inbox auto-sorting.

Two endpoints that mirror the suggest/confirm safety boundary in the service:
`/autosort/suggestions` reads and proposes, `/autosort/confirm` is the only one
that writes — and only for the inbox rows the caller explicitly lists, approved
through the same path the Inbox's Approve button uses. Both are gated on
OPENROUTER_API_KEY; without it the feature is off and returns 503 rather than
doing anything partial.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..db import get_db
from ..services import autosort as autosort_svc
from .inbox import approve_item

router = APIRouter(prefix="/autosort", tags=["autosort"])


@router.get("/status", response_model=schemas.AutosortStatus)
def status():
    """Whether the feature is configured. Lets the UI hide it when there's no
    key, without probing an endpoint that would 503."""
    return {
        "enabled": autosort_svc.autosort_available(),
        "model": settings.openrouter_model,
    }


@router.post("/suggestions", response_model=schemas.AutosortSuggestResponse)
def suggestions(db: Session = Depends(get_db)):
    """Propose funds for the pending inbox purchases. Read-only — makes no changes."""
    try:
        results = autosort_svc.suggest_assignments(db)
    except autosort_svc.AutosortDisabled:
        raise HTTPException(
            503, "auto-sort is disabled; set OPENROUTER_API_KEY to enable it"
        ) from None
    return {"suggestions": results}


@router.post("/confirm", response_model=schemas.AutosortConfirmResponse)
def confirm(body: schemas.AutosortConfirmRequest, db: Session = Depends(get_db)):
    """Approve the confirmed inbox rows into their funds. The only path that
    writes. Every change is checked before the first approval, so a bad row
    aborts the batch with nothing written."""
    if not autosort_svc.autosort_available():
        raise HTTPException(
            503, "auto-sort is disabled; set OPENROUTER_API_KEY to enable it"
        )
    try:
        changes = autosort_svc.validate_changes(
            db, [(c.inbox_id, c.fund_id) for c in body.changes]
        )
    except autosort_svc.InvalidDestination as e:
        raise HTTPException(400, str(e)) from e
    updated = [
        approve_item(db, inbox_id, fund_id, as_paycheck=False)
        for inbox_id, fund_id in changes
    ]
    return {"updated": updated}
