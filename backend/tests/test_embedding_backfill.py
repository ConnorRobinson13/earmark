"""Posting a transaction must not wait on the embedding service.

Writes store a NULL embedding and `suggest_fund` catches the missing rows up
before it searches, so a slow or unreachable Ollama costs a backfill pass rather
than the latency of somebody's click. These tests drive that from both ends: the
write path with the service hanging, and the read path with it back up.
"""
from __future__ import annotations

import hashlib
import time
from datetime import date

import pytest
from sqlalchemy import text

from app.constants import EMBEDDING_DIM


def _vector_for(prompt: str) -> list[float]:
    """A deterministic stand-in for the model: same text, same vector.

    Components straddle zero so cosine distance behaves like it does with a real
    embedding — identical merchants land on distance 0, which is what the
    similarity search is being asked about.
    """
    digest = hashlib.sha256(prompt.encode()).digest()
    return [
        (((digest[i % len(digest)] * (i + 1)) % 512) - 256) / 256.0
        for i in range(EMBEDDING_DIM)
    ]


class _FakeResponse:
    def __init__(self, embedding: list[float]):
        self._embedding = embedding

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"embedding": self._embedding}


class FakeOllama:
    """Stands in for `httpx.post` inside the embedding client.

    `up` flips the service on and off mid-test; `delay` makes it slow rather
    than merely absent, which is the case a connection-refused error would hide.
    `fail_after` lets it answer a few calls and then fall over, which is how a
    backfill pass finds out mid-flight that the model has gone away.
    """

    def __init__(self, *, up: bool = True, delay: float = 0.0, fail_after: int = -1):
        self.up = up
        self.delay = delay
        self.fail_after = fail_after
        self.prompts: list[str] = []

    def __call__(self, url: str, *, json: dict | None = None, timeout: float = 0.0):
        assert "/api/embeddings" in url, f"unexpected outbound request to {url}"
        prompt = (json or {})["prompt"]
        self.prompts.append(prompt)
        if self.delay:
            time.sleep(min(self.delay, timeout or self.delay))
        if not self.up or len(self.prompts) > self.fail_after >= 0:
            raise RuntimeError("ollama is down")
        return _FakeResponse(_vector_for(prompt))


@pytest.fixture()
def ollama(monkeypatch) -> FakeOllama:
    fake = FakeOllama()
    monkeypatch.setattr("app.services.embeddings.httpx.post", fake)
    return fake


def _embedding_of(engine, txn_id: int):
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT embedding FROM transactions WHERE id = :id"), {"id": txn_id}
        ).scalar_one()


def _quick_add(client, fund_id: int, merchant: str, amount: str = "12.00") -> int:
    resp = client.post(
        "/transactions/quick-add",
        json={
            "fund_id": fund_id,
            "amount": amount,
            "date": date.today().replace(day=15).isoformat(),
            "merchant": merchant,
            "type": "expense",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_quick_add_returns_promptly_while_the_embedding_service_hangs(client, ollama):
    """The acceptance criterion: posting does not block on the embedding call."""
    ollama.up = False
    ollama.delay = 5.0
    fund_id = client.post("/funds", json={"name": "Coffee"}).json()["id"]

    started = time.monotonic()
    _quick_add(client, fund_id, "Blue Bottle")
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, f"quick-add waited {elapsed:.1f}s on the embedding service"
    assert not ollama.prompts, "posting called the embedding service"


def test_inbox_approve_does_not_call_the_embedding_service(client, ollama):
    """The other path a person waits on posts through the same service."""
    from app.db import new_session
    from app.models import PlaidInbox

    fund_id = client.post("/funds", json={"name": "Groceries"}).json()["id"]
    session = new_session()
    try:
        item = PlaidInbox(
            plaid_transaction_id="plaid-approve-1",
            raw={},
            merchant="Trader Joe's",
            amount=42,
            date=date.today().replace(day=15),
        )
        session.add(item)
        session.commit()
        inbox_id = item.id
    finally:
        session.close()

    ollama.up = False
    ollama.delay = 5.0

    started = time.monotonic()
    resp = client.post(f"/inbox/{inbox_id}/approve", json={"fund_id": fund_id})
    elapsed = time.monotonic() - started

    assert resp.status_code == 200, resp.text
    assert elapsed < 1.0, f"approve waited {elapsed:.1f}s on the embedding service"
    assert not ollama.prompts, "approving called the embedding service"


def test_a_row_posted_while_ollama_was_down_is_embedded_once_it_returns(
    client, engine, ollama
):
    """Rows don't stay NULL forever — the next suggestion catches them up."""
    fund_id = client.post("/funds", json={"name": "Coffee"}).json()["id"]

    ollama.up = False
    txn_id = _quick_add(client, fund_id, "Blue Bottle")
    assert _embedding_of(engine, txn_id) is None

    ollama.up = True
    assert client.post("/suggest", json={"merchant": "anything"}).status_code == 200

    assert _embedding_of(engine, txn_id) is not None


def test_suggestion_still_matches_a_transaction_posted_earlier(client, ollama):
    """Suggestion quality is unchanged for anything posted more than a moment ago."""
    coffee = client.post("/funds", json={"name": "Coffee"}).json()
    client.post("/funds", json={"name": "Fuel"})
    _quick_add(client, coffee["id"], "Blue Bottle")

    body = client.post("/suggest", json={"merchant": "Blue Bottle"}).json()

    assert body["source"] == "vector"
    assert body["fund_id"] == coffee["id"]
    assert body["fund_name"] == "Coffee"


def test_backfill_is_skipped_when_the_service_has_just_failed(client, ollama):
    """A down service means every row would fail — don't ask once per row."""
    fund_id = client.post("/funds", json={"name": "Coffee"}).json()["id"]
    for n in range(3):
        _quick_add(client, fund_id, f"Merchant {n}")

    ollama.up = False
    assert client.post("/suggest", json={"merchant": "Blue Bottle"}).status_code == 200

    # Only the suggestion's own merchant was tried; once that failed the backfill
    # was skipped entirely rather than retried three more times.
    assert ollama.prompts == ["Blue Bottle"]


def test_backfill_stops_at_the_first_row_the_service_cannot_answer(client, ollama):
    """Losing the model mid-pass ends the pass, it doesn't grind through the rest."""
    fund_id = client.post("/funds", json={"name": "Coffee"}).json()["id"]
    for n in range(4):
        _quick_add(client, fund_id, f"Merchant {n}")

    # The suggestion's own merchant answers, then one backfill row, then nothing.
    ollama.fail_after = 2
    assert client.post("/suggest", json={"merchant": "Blue Bottle"}).status_code == 200

    assert len(ollama.prompts) == 3, ollama.prompts


def test_transactions_without_a_merchant_are_never_embedded(client, ollama):
    """Transfers carry no merchant text, so there is nothing to embed."""
    a = client.post("/funds", json={"name": "Coffee"}).json()["id"]
    b = client.post("/funds", json={"name": "Fuel"}).json()["id"]
    assert client.post(
        "/transactions/transfer",
        json={
            "from_fund_id": a,
            "to_fund_id": b,
            "amount": "10.00",
            "date": date.today().replace(day=15).isoformat(),
        },
    ).status_code == 201

    assert client.post("/suggest", json={"merchant": "Blue Bottle"}).status_code == 200

    assert ollama.prompts == ["Blue Bottle"]
