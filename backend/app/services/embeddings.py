"""Embedding client backed by Ollama on the host.

If Ollama is unreachable we silently return None — embeddings are best-effort,
not required for posting. Callers shouldn't fail just because the model is down.

Nothing here sits on the transaction write path any more: posting stores a NULL
embedding and `transactions.backfill_missing_embeddings` fills it in afterwards.
Both remaining callers are answering a request somebody is waiting on, which is
what the two timeouts below are sized against.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import settings

log = logging.getLogger(__name__)

# Generous enough for a cold `ollama` to page the model in on the first call.
EMBED_TIMEOUT = 10.0

# For requests a person is waiting on. Half a cold start still loses, but the
# caller degrades to a slower route rather than failing, and ten seconds of dead
# air on a categorization request is worse than one missed vector match.
INTERACTIVE_EMBED_TIMEOUT = 5.0


def embed_text(text: str, *, timeout: float = EMBED_TIMEOUT) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    resp = httpx.post(
        f"{settings.ollama_url}/api/embeddings",
        json={"model": settings.embedding_model, "prompt": text},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("embedding") or []


def embed_text_or_none(
    text: str, *, timeout: float = EMBED_TIMEOUT
) -> Optional[list[float]]:
    try:
        v = embed_text(text, timeout=timeout)
        return v or None
    except Exception as e:
        log.warning("embedding failed for %r: %s", text, e)
        return None
