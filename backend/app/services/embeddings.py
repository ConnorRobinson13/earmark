"""Embedding client backed by Ollama on the host.

If Ollama is unreachable we silently return None — embeddings are best-effort,
not required for posting. Callers shouldn't fail just because the model is down.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def embed_text(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    resp = httpx.post(
        f"{settings.ollama_url}/api/embeddings",
        json={"model": settings.embedding_model, "prompt": text},
        timeout=10.0,
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
