"""AI-assisted auto-sorting of the pending inbox via OpenRouter.

This proposes a fund for each pending Plaid purchase in the inbox, but it never
approves one on its own. The suggest/confirm split is the safety boundary:
`suggest_assignments` is read-only and asks the model for proposals, while
`validate_changes` checks a confirmed batch against the live funds and inbox
rows before the router approves anything. The model's output is never trusted;
every fund id and inbox id is re-checked here rather than taken from the reply.

All OpenRouter traffic is server-side. The API key comes from the
OPENROUTER_API_KEY environment variable (via `settings.openrouter_api_key`) and
never leaves the backend or appears in a response. When the key is absent the
feature reports itself unavailable and no outbound request is made — callers get
`AutosortDisabled`, not a half-working feature.

Only purchases are sorted. Income in the inbox is left alone: paychecks land in
Unassigned under the planned-income model, not in a fund.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Fund, InboxStatus, PlaidInbox

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Bounds on how much we hand the model in one pass. A suggestion request is one
# HTTP call listing this many of the oldest pending purchases; the rest wait for
# the next pass. Keeps the prompt (and the review list) a sane size.
SUGGEST_BATCH = 50

# Network timeout for the single OpenRouter call. Long enough for a cold model,
# short enough that a wedged provider degrades to "no suggestions" rather than
# hanging a request somebody is waiting on.
OPENROUTER_TIMEOUT = 30.0


class AutosortDisabled(RuntimeError):
    """Raised when the feature is used without OPENROUTER_API_KEY configured."""


class InvalidDestination(ValueError):
    """Raised when a confirmed change names a fund or inbox row that can't be
    approved into."""


@dataclass(frozen=True)
class Suggestion:
    """A proposed fund for one pending inbox purchase. Read-only; nothing has
    been written when this is produced."""

    inbox_id: int
    merchant: str
    amount: Decimal
    date: object  # datetime.date; kept loose to avoid importing for a hint
    suggested_fund_id: int | None  # None when the model declined or named no valid fund
    suggested_fund_name: str | None


def autosort_available() -> bool:
    """True when the feature is configured. The single gate every entry point
    checks, so "no key" means off everywhere rather than off in some places."""
    return bool((settings.openrouter_api_key or "").strip())


def _valid_funds(db: Session) -> dict[int, str]:
    """The funds a suggestion or a confirmation may target: active (non-archived)
    funds, by id. This is the allow-list the model's output is checked against."""
    funds = db.scalars(select(Fund).where(Fund.archived_at.is_(None))).all()
    return {f.id: f.name for f in funds}


def _pending_purchases(db: Session, limit: int) -> list[PlaidInbox]:
    """Pending inbox rows that are purchases — the queue worth sorting. Plaid
    signs purchases positive, so a negative amount is income and is skipped.
    Oldest first: the backlog is the point, not today's latest swipe."""
    return db.scalars(
        select(PlaidInbox)
        .where(PlaidInbox.status == InboxStatus.pending, PlaidInbox.amount > 0)
        .order_by(PlaidInbox.date.asc(), PlaidInbox.id.asc())
        .limit(limit)
    ).all()


def _build_prompt(items: list[PlaidInbox], funds: dict[int, str]) -> str:
    fund_lines = "\n".join(f"- {fid}: {name}" for fid, name in funds.items())
    item_lines = "\n".join(
        f"- {i.id}: merchant={i.merchant!r} amount=${abs(i.amount)} date={i.date.isoformat()}"
        for i in items
    )
    return (
        "You are sorting bank transactions into budget funds. For each "
        "transaction, pick the single best-matching fund ID from the list, or "
        "null if none fit.\n\n"
        f"Funds:\n{fund_lines}\n\n"
        f"Transactions:\n{item_lines}\n\n"
        "Respond with JSON only, an array of objects: "
        '[{"inbox_id": <id>, "fund_id": <id or null>}]. '
        "Only use inbox IDs and fund IDs from the lists above."
    )


def _chat(prompt: str) -> str:
    """One OpenRouter chat completion. Returns the message text.

    The key is sent as a bearer token and nowhere else; it is never logged or
    returned. Callers must have checked `autosort_available` first — this does
    too, so there is no way to reach the network without a key.
    """
    if not autosort_available():
        raise AutosortDisabled("OPENROUTER_API_KEY is not set")
    resp = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": settings.openrouter_model,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=OPENROUTER_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    return (body["choices"][0]["message"]["content"] or "").strip()


def _parse_pairs(text_out: str) -> list[tuple[int, int | None]]:
    """Pull (inbox_id, fund_id) pairs out of the model's reply.

    Lenient about surrounding prose — extracts the first JSON array — but strict
    about shape: anything that isn't an object with integer ids (fund_id may be
    null) is dropped rather than guessed at. The caller still validates the ids
    themselves; this only gets them into a usable form.
    """
    start = text_out.find("[")
    end = text_out.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        parsed = json.loads(text_out[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    pairs: list[tuple[int, int | None]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        iid = item.get("inbox_id")
        fid = item.get("fund_id")
        # Reject bools (an int subclass) and non-ints outright.
        if not isinstance(iid, int) or isinstance(iid, bool):
            continue
        if fid is not None and (not isinstance(fid, int) or isinstance(fid, bool)):
            continue
        pairs.append((iid, fid))
    return pairs


def suggest_assignments(db: Session, *, limit: int = SUGGEST_BATCH) -> list[Suggestion]:
    """Ask the model to sort the pending inbox purchases. Read-only.

    Returns one `Suggestion` for every pending purchase offered to the model, in
    queue order. A row the model matched to a *valid* active fund carries that
    fund. A row it declined, or named a fund that isn't valid, or that it didn't
    mention at all, comes back with no fund: the reviewer picks one by hand. A
    model pairing is never trusted for a row we didn't offer. Nothing is written
    here; the returned list is a proposal for the caller to review and confirm.
    """
    if not autosort_available():
        raise AutosortDisabled("OPENROUTER_API_KEY is not set")

    funds = _valid_funds(db)
    items = _pending_purchases(db, limit)
    if not items:
        return []
    if not funds:
        return [_suggestion(i, None, funds) for i in items]

    text_out = _chat(_build_prompt(items, funds))

    offered = {i.id for i in items}
    picked: dict[int, int] = {}
    for iid, fid in _parse_pairs(text_out):
        if fid is None or iid not in offered or iid in picked:
            # Declined, hallucinated, or a duplicate — leave the row unassigned.
            continue
        if fid not in funds:
            # Named a fund that isn't a valid destination. Drop it; we do not
            # fall back to a guess, because an unvalidated assignment is exactly
            # what the confirmation step exists to prevent.
            continue
        picked[iid] = fid

    return [_suggestion(i, picked.get(i.id), funds) for i in items]


def _suggestion(
    item: PlaidInbox, fund_id: int | None, funds: dict[int, str]
) -> Suggestion:
    return Suggestion(
        inbox_id=item.id,
        merchant=item.merchant,
        amount=item.amount,
        date=item.date,
        suggested_fund_id=fund_id,
        suggested_fund_name=funds[fund_id] if fund_id is not None else None,
    )


def validate_changes(
    db: Session, changes: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Check confirmed (inbox_id, fund_id) pairs before anything is approved.

    Every pair is checked against the live funds and the live inbox *before* the
    caller approves any of them, so a single bad row or destination aborts the
    whole batch and leaves the ledger untouched. Returns the pairs unchanged so
    the caller can approve them in order.
    """
    if not changes:
        return []

    funds = _valid_funds(db)
    seen: set[int] = set()
    for inbox_id, fund_id in changes:
        if inbox_id in seen:
            raise InvalidDestination(f"inbox item {inbox_id} is listed twice")
        seen.add(inbox_id)
        if fund_id not in funds:
            raise InvalidDestination(f"fund {fund_id} is not a valid destination")
        item = db.get(PlaidInbox, inbox_id)
        if item is None or item.status != InboxStatus.pending:
            raise InvalidDestination(f"inbox item {inbox_id} is not pending")
        if item.amount <= 0:
            raise InvalidDestination(f"inbox item {inbox_id} is income, not a purchase")
    return changes
