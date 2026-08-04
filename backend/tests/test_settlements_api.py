"""End-to-end: settling a goal contribution, and undoing it.

Settling moves real cash between two accounts; undoing it moves the same cash
back. These tests pin that round trip through the HTTP layer — every account
the settlement touched must read exactly what it read before — plus the input
rules the handler enforces on the way in.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def _accounts_by_name(client) -> dict[str, Decimal]:
    return {a["name"]: Decimal(a["current_balance"]) for a in client.get("/accounts").json()}


def _goal_backed_by(client, account_id: int, *, name: str = "New Roof") -> int:
    return client.post(
        "/funds",
        json={"name": name, "kind": "goal", "backed_by_account_id": account_id},
    ).json()["id"]


def test_settle_then_undo_restores_every_account_balance(client):
    today = date.today().isoformat()
    checking = client.post(
        "/accounts", json={"name": "Checking", "type": "checking", "current_balance": "2000.00"}
    ).json()["id"]
    savings = client.post(
        "/accounts", json={"name": "Savings", "type": "savings", "current_balance": "500.00"}
    ).json()["id"]
    goal_id = _goal_backed_by(client, savings)
    client.post("/transactions/assign", json={"fund_id": goal_id, "amount": "300.00", "date": today})

    before = _accounts_by_name(client)

    settled = client.post(
        f"/settlements/goal/{goal_id}",
        json={"amount": "300.00", "from_account_id": checking, "settled_at": today},
    )
    assert settled.status_code == 201
    moved = _accounts_by_name(client)
    assert moved["Checking"] == before["Checking"] - Decimal("300.00")
    assert moved["Savings"] == before["Savings"] + Decimal("300.00")

    assert client.delete(f"/settlements/{settled.json()['id']}").status_code == 204
    assert _accounts_by_name(client) == before


def test_settle_reduces_pending_and_undo_restores_it(client):
    """The To-Move panel's view of the same round trip."""
    today = date.today().isoformat()
    checking = client.post(
        "/accounts", json={"name": "Checking", "type": "checking", "current_balance": "2000.00"}
    ).json()["id"]
    savings = client.post(
        "/accounts", json={"name": "Savings", "type": "savings", "current_balance": "0"}
    ).json()["id"]
    goal_id = _goal_backed_by(client, savings)
    client.post("/transactions/assign", json={"fund_id": goal_id, "amount": "300.00", "date": today})

    pending = client.get("/settlements/pending").json()
    assert [(p["goal_id"], Decimal(p["pending_amount"])) for p in pending] == [
        (goal_id, Decimal("300.00"))
    ]
    assert pending[0]["to_account_id"] == savings
    assert pending[0]["suggested_from_account_id"] == checking

    body = client.post(
        f"/settlements/goal/{goal_id}",
        json={"amount": "120.00", "from_account_id": checking, "settled_at": today},
    ).json()
    assert body["goal_id"] == goal_id
    assert body["from_account_id"] == checking
    assert body["to_account_id"] == savings
    assert body["settled_at"] == today
    assert Decimal(body["amount"]) == Decimal("120.00")

    still_pending = client.get("/settlements/pending").json()
    assert Decimal(still_pending[0]["pending_amount"]) == Decimal("180.00")

    client.delete(f"/settlements/{body['id']}")
    assert Decimal(client.get("/settlements/pending").json()[0]["pending_amount"]) == Decimal(
        "300.00"
    )


def test_settle_rejects_non_positive_amount(client):
    today = date.today().isoformat()
    checking = client.post(
        "/accounts", json={"name": "Checking", "type": "checking", "current_balance": "2000.00"}
    ).json()["id"]
    savings = client.post(
        "/accounts", json={"name": "Savings", "type": "savings", "current_balance": "500.00"}
    ).json()["id"]
    goal_id = _goal_backed_by(client, savings)
    client.post("/transactions/assign", json={"fund_id": goal_id, "amount": "300.00", "date": today})
    before = _accounts_by_name(client)

    for amount in ("0", "-25.00"):
        r = client.post(
            f"/settlements/goal/{goal_id}",
            json={"amount": amount, "from_account_id": checking, "settled_at": today},
        )
        assert r.status_code == 400, amount

    # Rejected settlements leave nothing behind: no money moved, and pending is
    # untouched — a recorded settlement would have drawn it down.
    assert _accounts_by_name(client) == before
    assert Decimal(client.get("/settlements/pending").json()[0]["pending_amount"]) == Decimal(
        "300.00"
    )


def test_settle_unknown_goal_is_404(client):
    r = client.post("/settlements/goal/9999", json={"amount": "10.00"})
    assert r.status_code == 404


def test_settle_on_a_non_goal_fund_is_404(client):
    fund_id = client.post("/funds", json={"name": "Groceries"}).json()["id"]
    r = client.post(f"/settlements/goal/{fund_id}", json={"amount": "10.00"})
    assert r.status_code == 404


def test_undo_unknown_settlement_is_404(client):
    assert client.delete("/settlements/9999").status_code == 404


def test_settling_into_the_account_the_cash_came_from_is_a_no_op(client):
    """Source and destination can be the same account (a goal backed by
    checking). Nothing physically moved, so no balance may either — and undoing
    it must not conjure money out of the round trip."""
    today = date.today().isoformat()
    checking = client.post(
        "/accounts", json={"name": "Checking", "type": "checking", "current_balance": "2000.00"}
    ).json()["id"]
    goal_id = _goal_backed_by(client, checking)
    before = _accounts_by_name(client)

    settled = client.post(
        f"/settlements/goal/{goal_id}",
        json={"amount": "300.00", "from_account_id": checking, "settled_at": today},
    ).json()
    assert _accounts_by_name(client) == before

    client.delete(f"/settlements/{settled['id']}")
    assert _accounts_by_name(client) == before


def test_settle_without_a_source_account_only_credits_the_goal_account(client):
    """`from_account_id` is optional — the user may not know where the cash came
    from. The destination still moves, and undoing still puts it back."""
    today = date.today().isoformat()
    savings = client.post(
        "/accounts", json={"name": "Savings", "type": "savings", "current_balance": "500.00"}
    ).json()["id"]
    goal_id = _goal_backed_by(client, savings)
    before = _accounts_by_name(client)

    settled = client.post(
        f"/settlements/goal/{goal_id}", json={"amount": "75.00", "settled_at": today}
    ).json()
    assert settled["from_account_id"] is None
    assert _accounts_by_name(client)["Savings"] == before["Savings"] + Decimal("75.00")

    client.delete(f"/settlements/{settled['id']}")
    assert _accounts_by_name(client) == before
