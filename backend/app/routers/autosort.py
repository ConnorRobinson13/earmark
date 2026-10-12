"""AI-assisted transaction auto-sorting.

Two endpoints that mirror the suggest/confirm safety boundary in the service:
`/autosort/suggestions` reads and proposes, `/autosort/confirm` is the only one
that writes — and only for the changes the caller explicitly lists. Both are
gated on OPENROUTER_API_KEY; without it the feature is off and returns 503
rather than doing anything partial.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..config import settings
from ..db import get_db
from ..services import autosort as autosort_svc

router = APIRouter(prefix="/autosort", tags=["autosort"])


@router.get("/status", response_model=schemas.AutosortStatus)
def status():
    """Whether the feature is configured. Lets the UI hide it when there's no
    key, without probing an endpoint that would 503."""
    return {"enabled": autosort_svc.autosort_available(), "model": settings.openrouter_model}


@router.post("/suggestions", response_model=schemas.AutosortSuggestResponse)
def suggestions(db: Session = Depends(get_db)):
    """Propose funds for the unassigned expenses. Read-only — makes no changes."""
    try:
        results = autosort_svc.suggest_assignments(db)
    except autosort_svc.AutosortDisabled:
        raise HTTPException(503, "auto-sort is disabled; set OPENROUTER_API_KEY to enable it")
    return {"suggestions": results}


@router.post("/confirm", response_model=schemas.AutosortConfirmResponse)
def confirm(body: schemas.AutosortConfirmRequest, db: Session = Depends(get_db)):
    """Apply the confirmed assignments. The only path that mutates a fund_id."""
    if not autosort_svc.autosort_available():
        raise HTTPException(503, "auto-sort is disabled; set OPENROUTER_API_KEY to enable it")
    try:
        updated = autosort_svc.apply_assignments(
            db, [(c.transaction_id, c.fund_id) for c in body.changes]
        )
    except autosort_svc.InvalidDestination as e:
        # Nothing was written — apply_assignments validates the whole batch
        # before mutating — so this is a clean 400.
        raise HTTPException(400, str(e))
    db.commit()
    for t in updated:
        db.refresh(t)
    return {"updated": updated}
