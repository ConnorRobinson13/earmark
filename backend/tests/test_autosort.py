"""AI-assisted transaction auto-sorting.

These pin the three things that make the feature safe to ship:

* it is gated on OPENROUTER_API_KEY — no key means no outbound call and a 503,
  never a half-working endpoint;
* the model's output is never trusted: a hallucinated transaction, an invalid or
  archived fund, or malformed JSON is dropped rather than assigned;
* nothing is written until the caller confirms — asking for suggestions mutates
  no row, and a confirmation that names a bad fund aborts the whole batch.

The provider is mocked throughout (`FakeOpenRouter` stands in for
`httpx.post`), so the suite makes no live API call and needs no real key.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.models import Fund, FundKind, Transaction, TxType


class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class FakeOpenRouter:
    """Stands in for `httpx.post` inside the auto-sort service.

    `content` is what the model "replies"; tests set it after seeding so it can
    reference the real transaction ids. Every call is recorded so a test can
    assert the request the service built — the pinned model id and the key sent
    as a bearer token — and so a gating test can assert nothing went out at all.
    """

    def __init__(self) -> None:
        self.content = "[]"
        self.calls: list[dict] = []

    def __call__(self, url: str, *, headers=None, json=None, timeout=None):
        assert "openrouter.ai" in url, f"unexpected outbound request to {url}"
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return _FakeResponse(self.content)


@pytest.fixture()
def openrouter(monkeypatch) -> FakeOpenRouter:
    """Mock the HTTP client and hand the feature a key, so the provider is never
    actually reached. Tests that exercise the no-key path override the key."""
    from app.services import autosort

    fake = FakeOpenRouter()
    monkeypatch.setattr(autosort.httpx, "post", fake)
    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(autosort.settings, "openrouter_model", "typesafe/jev-router")
    return fake


def _seed(*, archived: bool = False):
    """Two active funds (+ optionally an archived one) and a mix of transactions:
    two unassigned expenses, one already-assigned expense, one unassigned income.
    Returns the ids the tests need."""
    from app.db import new_session

    with new_session() as s:
        groceries = Fund(name="Groceries", kind=FundKind.operational)
        fuel = Fund(name="Fuel", kind=FundKind.operational)
        s.add_all([groceries, fuel])
        funds = {"groceries": groceries, "fuel": fuel}
        if archived:
            from datetime import datetime, timezone

            old = Fund(name="Old", kind=FundKind.operational)
            old.archived_at = datetime.now(timezone.utc)
            s.add(old)
            funds["old"] = old
        s.flush()

        unassigned_a = Transaction(
            fund_id=None, type=TxType.expense, amount=Decimal("-42.00"),
            date=date(2026, 3, 1), merchant="Trader Joe's",
            plaid_transaction_id="plaid-a",
        )
        unassigned_b = Transaction(
            fund_id=None, type=TxType.expense, amount=Decimal("-30.00"),
            date=date(2026, 3, 2), merchant="Shell",
        )
        already_assigned = Transaction(
            fund_id=groceries.id, type=TxType.expense, amount=Decimal("-10.00"),
            date=date(2026, 3, 3), merchant="Costco",
        )
        unassigned_income = Transaction(
            fund_id=None, type=TxType.income, amount=Decimal("1000.00"),
            date=date(2026, 3, 4), merchant="Paycheck",
        )
        s.add_all([unassigned_a, unassigned_b, already_assigned, unassigned_income])
        s.flush()
        ids = {
            "groceries": groceries.id,
            "fuel": fuel.id,
            "old": funds["old"].id if archived else None,
            "txn_a": unassigned_a.id,
            "txn_b": unassigned_b.id,
            "assigned": already_assigned.id,
            "income": unassigned_income.id,
        }
        s.commit()
    return ids


def _fund_id_of(txn_id: int):
    from app.db import new_session

    with new_session() as s:
        return s.get(Transaction, txn_id).fund_id


# --------------------------------------------------------------------------
# Gating: no key
# --------------------------------------------------------------------------

def test_status_reports_disabled_without_a_key(client, monkeypatch):
    from app.services import autosort

    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    body = client.get("/autosort/status").json()
    assert body["enabled"] is False
    assert body["model"] == "typesafe/jev-router"


def test_suggestions_is_gated_off_without_a_key(client, monkeypatch):
    """No key: a clean 503 and — the point — no outbound request is attempted."""
    from app.services import autosort

    fake = FakeOpenRouter()
    monkeypatch.setattr(autosort.httpx, "post", fake)
    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    _seed()

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 503
    assert fake.calls == [], "called the provider with no key configured"


def test_confirm_is_gated_off_without_a_key(client, monkeypatch):
    from app.services import autosort

    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    ids = _seed()

    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"transaction_id": ids["txn_a"], "fund_id": ids["groceries"]}]},
    )
    assert resp.status_code == 503
    assert _fund_id_of(ids["txn_a"]) is None, "mutated with the feature gated off"


# --------------------------------------------------------------------------
# Suggestions: read-only, validated, pinned model
# --------------------------------------------------------------------------

def test_suggestions_use_the_pinned_model_and_a_server_side_key(client, openrouter):
    ids = _seed()
    openrouter.content = json.dumps(
        [{"transaction_id": ids["txn_a"], "fund_id": ids["groceries"]}]
    )

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 200, resp.text

    assert len(openrouter.calls) == 1
    call = openrouter.calls[0]
    assert call["json"]["model"] == "typesafe/jev-router"
    assert call["headers"].get("Authorization") == "Bearer test-key"


def test_suggestions_do_not_change_any_assignment(client, openrouter):
    """The read-only half: a suggestion proposes, it never writes."""
    ids = _seed()
    openrouter.content = json.dumps([
        {"transaction_id": ids["txn_a"], "fund_id": ids["fuel"]},
        {"transaction_id": ids["txn_b"], "fund_id": ids["groceries"]},
    ])

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()["suggestions"]
    assert {s["transaction_id"] for s in body} == {ids["txn_a"], ids["txn_b"]}

    # Nothing moved: both are still unassigned after merely asking.
    assert _fund_id_of(ids["txn_a"]) is None
    assert _fund_id_of(ids["txn_b"]) is None


def test_suggestions_only_cover_unassigned_expenses(client, openrouter):
    """Already-assigned expenses and unassigned income are left out of the ask."""
    ids = _seed()
    # The model is never even offered these; if it names them anyway they drop.
    openrouter.content = json.dumps([
        {"transaction_id": ids["assigned"], "fund_id": ids["fuel"]},
        {"transaction_id": ids["income"], "fund_id": ids["fuel"]},
        {"transaction_id": ids["txn_a"], "fund_id": ids["groceries"]},
    ])

    body = client.post("/autosort/suggestions").json()["suggestions"]
    assert {s["transaction_id"] for s in body} == {ids["txn_a"]}

    prompt = openrouter.calls[0]["json"]["messages"][0]["content"]
    assert "Trader Joe's" in prompt and "Shell" in prompt
    assert "Costco" not in prompt and "Paycheck" not in prompt


def test_invalid_model_output_is_dropped_not_assigned(client, openrouter):
    """A hallucinated transaction, an unknown fund and an archived fund are all
    discarded; only the one valid pairing survives."""
    ids = _seed(archived=True)
    openrouter.content = json.dumps([
        {"transaction_id": 999999, "fund_id": ids["groceries"]},   # no such txn
        {"transaction_id": ids["txn_a"], "fund_id": 888888},        # no such fund
        {"transaction_id": ids["txn_b"], "fund_id": ids["old"]},    # archived fund
        {"transaction_id": ids["txn_a"], "fund_id": ids["fuel"]},   # the one good one
    ])

    body = client.post("/autosort/suggestions").json()["suggestions"]
    assert body == [{
        "transaction_id": ids["txn_a"],
        "merchant": "Trader Joe's",
        "amount": "-42.00",
        "date": "2026-03-01",
        "current_fund_id": None,
        "suggested_fund_id": ids["fuel"],
        "suggested_fund_name": "Fuel",
    }]


def test_malformed_model_output_yields_no_suggestions(client, openrouter):
    """Not JSON, null fund ids and non-integer ids all come back empty, not crash."""
    _seed()
    openrouter.content = "the model forgot to answer in JSON"
    assert client.post("/autosort/suggestions").json()["suggestions"] == []


# --------------------------------------------------------------------------
# Confirm: the only writer, validated, atomic
# --------------------------------------------------------------------------

def test_confirm_applies_only_the_listed_change_and_preserves_the_rest(client, openrouter):
    ids = _seed()

    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"transaction_id": ids["txn_a"], "fund_id": ids["groceries"]}]},
    )
    assert resp.status_code == 200, resp.text

    (updated,) = resp.json()["updated"]
    assert updated["fund_id"] == ids["groceries"]
    # Everything but the fund is preserved exactly as posted.
    assert updated["amount"] == "-42.00"
    assert updated["date"] == "2026-03-01"
    assert updated["merchant"] == "Trader Joe's"
    assert updated["plaid_transaction_id"] == "plaid-a"

    assert _fund_id_of(ids["txn_a"]) == ids["groceries"]
    # The unconfirmed transaction is untouched.
    assert _fund_id_of(ids["txn_b"]) is None


def test_confirm_rejects_an_invalid_destination_without_mutating(client, openrouter):
    """A bad fund in the batch aborts the whole batch — no partial write."""
    ids = _seed(archived=True)

    resp = client.post(
        "/autosort/confirm",
        json={"changes": [
            {"transaction_id": ids["txn_a"], "fund_id": ids["groceries"]},  # valid
            {"transaction_id": ids["txn_b"], "fund_id": ids["old"]},        # archived
        ]},
    )
    assert resp.status_code == 400

    # Neither moved, including the otherwise-valid first change.
    assert _fund_id_of(ids["txn_a"]) is None
    assert _fund_id_of(ids["txn_b"]) is None


def test_confirm_rejects_an_unknown_fund_without_mutating(client, openrouter):
    ids = _seed()
    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"transaction_id": ids["txn_a"], "fund_id": 777777}]},
    )
    assert resp.status_code == 400
    assert _fund_id_of(ids["txn_a"]) is None
