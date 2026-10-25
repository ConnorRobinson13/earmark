"""AI-assisted transaction auto-sorting via OpenRouter.

This proposes a fund for each unassigned transaction, but it never changes an
assignment on its own. The suggest/confirm split is the safety boundary:
`suggest_assignments` is read-only and asks the model for proposals, while
`apply_assignments` is the only writer and re-validates every fund id against
the live funds rather than trusting whatever the model returned. A caller must
pass an explicit list of changes to `apply_assignments`; there is no path from a
suggestion to a write that doesn't go through that confirmation step.

All OpenRouter traffic is server-side. The API key comes from the
OPENROUTER_API_KEY environment variable (via `settings.openrouter_api_key`) and
never leaves the backend or appears in a response. When the key is absent the
feature reports itself unavailable and no outbound request is made — callers get
`AutosortDisabled`, not a half-working feature.

Only the fund assignment changes. `apply_assignments` touches `fund_id` and
nothing else, so a transaction's amount, date, merchant and Plaid id are
preserved exactly as posted.
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
from ..models import Fund, Transaction, TxType

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Bounds on how much we hand the model in one pass. A suggestion request is one
# HTTP call listing this many of the oldest-unassigned transactions; the rest
# wait for the next pass. Keeps the prompt (and the review list) a sane size.
SUGGEST_BATCH = 50

# Network timeout for the single OpenRouter call. Long enough for a cold model,
# short enough that a wedged provider degrades to "no suggestions" rather than
# hanging a request somebody is waiting on.
OPENROUTER_TIMEOUT = 30.0


class AutosortDisabled(RuntimeError):
    """Raised when the feature is used without OPENROUTER_API_KEY configured."""


class InvalidDestination(ValueError):
    """Raised when a confirmed change names a fund that isn't a valid target."""


@dataclass(frozen=True)
class Suggestion:
    """A proposed fund for one unassigned transaction. Read-only; nothing has
    been written when this is produced."""

    transaction_id: int
    merchant: str
    amount: Decimal
    date: object  # datetime.date; kept loose to avoid importing for a hint
    current_fund_id: int | None
    suggested_fund_id: int
    suggested_fund_name: str


def autosort_available() -> bool:
    """True when the feature is configured. The single gate every entry point
    checks, so "no key" means off everywhere rather than off in some places."""
    return bool((settings.openrouter_api_key or "").strip())


def _valid_funds(db: Session) -> dict[int, str]:
    """The funds a suggestion or a confirmation may target: active (non-archived)
    funds, by id. This is the allow-list the model's output is checked against."""
    funds = db.scalars(select(Fund).where(Fund.archived_at.is_(None))).all()
    return {f.id: f.name for f in funds}


def _unassigned_expenses(db: Session, limit: int) -> list[Transaction]:
    """Expenses that never landed in a fund — the rows worth sorting.

    Income left in Unassigned is deliberate (paychecks under the planned-income
    model) and transfers/assignments carry their own funds, so an expense with a
    NULL fund is the orphan this feature exists to clear. Oldest first: the long
    tail of un-sorted history is the point, not today's latest swipe.
    """
    return db.scalars(
        select(Transaction)
        .where(Transaction.fund_id.is_(None), Transaction.type == TxType.expense)
        .order_by(Transaction.date.asc(), Transaction.id.asc())
        .limit(limit)
    ).all()


def _build_prompt(txns: list[Transaction], funds: dict[int, str]) -> str:
    fund_lines = "\n".join(f"- {fid}: {name}" for fid, name in funds.items())
    txn_lines = "\n".join(
        f"- {t.id}: merchant={t.merchant!r} amount=${abs(t.amount)} date={t.date.isoformat()}"
        for t in txns
    )
    return (
        "You are sorting bank transactions into budget funds. For each "
        "transaction, pick the single best-matching fund ID from the list, or "
        "null if none fit.\n\n"
        f"Funds:\n{fund_lines}\n\n"
        f"Transactions:\n{txn_lines}\n\n"
        "Respond with JSON only, an array of objects: "
        '[{"transaction_id": <id>, "fund_id": <id or null>}]. '
        "Only use transaction IDs and fund IDs from the lists above."
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
    """Pull (transaction_id, fund_id) pairs out of the model's reply.

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
        tid = item.get("transaction_id")
        fid = item.get("fund_id")
        # Reject bools (an int subclass) and non-ints outright.
        if not isinstance(tid, int) or isinstance(tid, bool):
            continue
        if fid is not None and (not isinstance(fid, int) or isinstance(fid, bool)):
            continue
        pairs.append((tid, fid))
    return pairs


def suggest_assignments(db: Session, *, limit: int = SUGGEST_BATCH) -> list[Suggestion]:
    """Ask the model to sort the unassigned expenses. Read-only.

    Returns one `Suggestion` per transaction the model matched to a *valid*
    active fund. A pairing is discarded — never surfaced — when the transaction
    isn't one we actually offered, the fund id isn't a current valid fund, or the
    model declined (fund_id null). Nothing is written here; the returned list is
    a proposal for the caller to confirm.
    """
    if not autosort_available():
        raise AutosortDisabled("OPENROUTER_API_KEY is not set")

    funds = _valid_funds(db)
    txns = _unassigned_expenses(db, limit)
    if not funds or not txns:
        return []

    by_id = {t.id: t for t in txns}
    text_out = _chat(_build_prompt(txns, funds))

    suggestions: list[Suggestion] = []
    seen: set[int] = set()
    for tid, fid in _parse_pairs(text_out):
        if fid is None:
            continue
        t = by_id.get(tid)
        if t is None or tid in seen:
            # Hallucinated or duplicated a transaction id — not one we offered.
            continue
        if fid not in funds:
            # Named a fund that isn't a valid destination. Drop it; we do not
            # fall back to a guess, because an unvalidated assignment is exactly
            # what the confirmation step exists to prevent.
            continue
        seen.add(tid)
        suggestions.append(
            Suggestion(
                transaction_id=t.id,
                merchant=t.merchant,
                amount=t.amount,
                date=t.date,
                current_fund_id=t.fund_id,
                suggested_fund_id=fid,
                suggested_fund_name=funds[fid],
            )
        )
    return suggestions


def apply_assignments(db: Session, changes: list[tuple[int, int]]) -> list[Transaction]:
    """Apply confirmed (transaction_id, fund_id) assignments. The only writer.

    Validates every change against the live funds *before* mutating anything, so
    a single bad destination aborts the whole batch and leaves the ledger
    untouched — there is no partially-applied state. Only `fund_id` is set; the
    amount, date, merchant and Plaid id are preserved exactly as posted.
    """
    if not changes:
        return []

    funds = _valid_funds(db)

    # Validate first, mutate second: resolve every row and reject any invalid
    # fund or missing transaction before a single assignment is written.
    resolved: list[tuple[Transaction, int]] = []
    for tid, fid in changes:
        if fid not in funds:
            raise InvalidDestination(f"fund {fid} is not a valid destination")
        t = db.get(Transaction, tid)
        if t is None:
            raise InvalidDestination(f"transaction {tid} does not exist")
        resolved.append((t, fid))

    for t, fid in resolved:
        t.fund_id = fid
    db.flush()
    return [t for t, _ in resolved]
