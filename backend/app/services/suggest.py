"""Fund suggestion: nearest past transaction by embedding, computed locally."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from .embeddings import backfill_missing_embeddings, embed_text_or_none

VECTOR_MATCH_THRESHOLD = 0.35  # cosine distance — lower means more similar


def suggest_fund(db: Session, merchant: str) -> tuple[int | None, str | None, str]:
    """Return (fund_id, fund_name, source) where source ∈ {"vector","none"}.

    There is no hosted-model fallback. Suggestions come from local embeddings
    alone, so nothing about a transaction leaves the machine here. The AI
    auto-sort in services/autosort.py is a separate, opt-in path (OpenRouter).
    """
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

    return None, None, "none"
