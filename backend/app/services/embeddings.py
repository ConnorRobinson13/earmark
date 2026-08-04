"""Transaction embeddings: the Ollama client, and catching up rows without one.

If Ollama is unreachable we silently return None — embeddings are best-effort,
not required for posting. Callers shouldn't fail just because the model is down.

Nothing here sits on the transaction write path. Posting stores a NULL embedding
and `backfill_missing_embeddings` fills it in afterwards, which is why the
backfill lives beside the client rather than in the posting service: that module
no longer knows embeddings exist.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
from sqlalchemy import func, select

from ..config import settings
from ..db import new_session
from ..models import Transaction

log = logging.getLogger(__name__)

# Every remaining caller is answering a request somebody is waiting on. Five
# seconds loses a cold `ollama` still paging the model in, but the caller
# degrades to a slower route rather than failing, and ten seconds of dead air on
# a categorization request is worse than one missed vector match.
EMBED_TIMEOUT = 5.0

# The backfill runs inside one of those requests, so it is bounded by time
# rather than by completeness: whatever it doesn't reach, the next pass picks
# up. Checked between rows, so a single slow row can overshoot it by up to one
# `EMBED_TIMEOUT`.
BACKFILL_BUDGET_SECONDS = 3.0

# Cap on rows pulled per pass. A bound on the query, not on the work — the
# budget above is what actually stops us.
BACKFILL_BATCH = 500


def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    resp = httpx.post(
        f"{settings.ollama_url}/api/embeddings",
        json={"model": settings.embedding_model, "prompt": text},
        timeout=EMBED_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("embedding") or []


def embed_text_or_none(text: str) -> Optional[list[float]]:
    try:
        v = embed_text(text)
        return v or None
    except Exception as e:
        log.warning("embedding failed for %r: %s", text, e)
        return None


def backfill_missing_embeddings(
    *, budget_seconds: float = BACKFILL_BUDGET_SECONDS
) -> int:
    """Embed transactions that were posted without one. Returns rows filled.

    Owns its session and commits it, rather than borrowing the caller's. The
    caller is `suggest_fund`, which serves read-only requests that never commit;
    work this expensive shouldn't be thrown away because of that, and it has no
    business riding along inside somebody else's transaction either.

    Newest first: a recent transaction is the likeliest useful neighbour, so if
    the budget runs out it should run out on the old rows.
    """
    started = time.monotonic()
    filled = 0
    db = new_session()
    try:
        pending = db.scalars(
            select(Transaction)
            .where(
                Transaction.embedding.is_(None),
                # Transfers and assignments carry no merchant text; neither does
                # a merchant that is only whitespace, which the client strips.
                func.btrim(Transaction.merchant) != "",
            )
            .order_by(Transaction.id.desc())
            .limit(BACKFILL_BATCH)
        ).all()

        for t in pending:
            if time.monotonic() - started >= budget_seconds:
                log.info(
                    "embedding backfill out of budget after %d rows, %d still pending",
                    filled,
                    len(pending) - filled,
                )
                break
            try:
                vec = embed_text(t.merchant)
            except Exception as e:
                # Ollama is down or ill, so every remaining row would fail the
                # same way. One refused connection is enough to know the rest of
                # the pass is wasted.
                log.warning("embedding backfill stopped after %d rows: %s", filled, e)
                break
            if not vec:
                # The model answered but had nothing for this text. Skip rather
                # than stop: breaking here would let one unembeddable row wedge
                # every older row out of the backfill permanently, because the
                # scan runs newest-first and would never get past it.
                log.warning("no embedding for transaction %s (%r)", t.id, t.merchant)
                continue
            t.embedding = vec
            filled += 1

        if filled:
            db.commit()
    finally:
        db.close()
    return filled
