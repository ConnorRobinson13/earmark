"""Fund suggestion: vector similarity first, LLM fallback."""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Fund
from .embeddings import backfill_missing_embeddings, embed_text_or_none

log = logging.getLogger(__name__)

VECTOR_MATCH_THRESHOLD = 0.35  # cosine distance — lower means more similar


def suggest_fund(
    db: Session, merchant: str, amount: Optional[Decimal] = None
) -> tuple[Optional[int], Optional[str], str]:
    """Return (fund_id, fund_name, source) where source ∈ {"vector","llm","none"}."""
    merchant = (merchant or "").strip()
    if not merchant:
        return None, None, "none"

    vec = embed_text_or_none(merchant)
    if vec is not None:
        # Writes leave `embedding` NULL so posting doesn't wait on Ollama, which
        # makes recent transactions invisible to the search below — a neighbour
        # that isn't embedded is a neighbour we can't find. Catch them up first.
        # Only reached when the call above just succeeded, so the model is up.
        backfill_missing_embeddings()

        # nearest past transaction by cosine distance with a tagged fund
        row = db.execute(
            text(
                """
                SELECT t.fund_id, f.name, t.embedding <=> CAST(:vec AS vector) AS dist
                FROM transactions t
                JOIN funds f ON f.id = t.fund_id
                WHERE t.embedding IS NOT NULL AND t.fund_id IS NOT NULL
                ORDER BY t.embedding <=> CAST(:vec AS vector) ASC
                LIMIT 1
                """
            ),
            {"vec": str(vec)},
        ).first()
        if row and row.dist is not None and row.dist <= VECTOR_MATCH_THRESHOLD:
            return row.fund_id, row.name, "vector"

    # LLM fallback
    if settings.anthropic_api_key:
        try:
            fund_id, fund_name = _llm_suggest(db, merchant, amount)
            if fund_id is not None:
                return fund_id, fund_name, "llm"
        except Exception as e:
            log.warning("llm suggest failed: %s", e)

    return None, None, "none"


def _llm_suggest(
    db: Session, merchant: str, amount: Optional[Decimal]
) -> tuple[Optional[int], Optional[str]]:
    funds = db.scalars(select(Fund).where(Fund.archived_at.is_(None))).all()
    if not funds:
        return None, None

    fund_list = "\n".join(f"- {f.id}: {f.name} ({f.kind.value})" for f in funds)
    prompt = (
        "Given a transaction, return the single best-matching fund ID from the list.\n\n"
        f"Transaction:\n  Merchant: {merchant}\n"
        + (f"  Amount: ${amount}\n" if amount is not None else "")
        + f"\nFunds:\n{fund_list}\n\n"
        'Respond with JSON only: {"fund_id": <id>} or {"fund_id": null} if none fit.'
    )
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": settings.anthropic_model,
            "max_tokens": 100,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    text_out = body["content"][0]["text"].strip()
    # be lenient — extract first {...}
    start = text_out.find("{")
    end = text_out.rfind("}")
    if start == -1 or end == -1:
        return None, None
    parsed = json.loads(text_out[start : end + 1])
    fund_id = parsed.get("fund_id")
    if fund_id is None:
        return None, None
    fund = db.get(Fund, fund_id)
    return (fund.id, fund.name) if fund else (None, None)
