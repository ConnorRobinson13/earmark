"""Moving an already-assigned transaction to a different fund, over the HTTP layer.

The feature re-tags one transaction's fund without disturbing anything else:
the amount leaves the old fund and lands on the new one, the row keeps its
identity (same id, amount, date, merchant, Plaid id), no second row appears, and
an invalid destination is refused without touching the ledger.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def _make_fund(client, name: str) -> int:
    return client.post("/funds", json={"name": name}).json()["id"]


def _assigned_expense(client, fund_id: int, amount: str, merchant: str) -> dict:
    """Assign money to a fund, then spend from it. Returns the expense row."""
    today = date.today().replace(day=15).isoformat()
    client.post(
        "/transactions/assign",
        json={"fund_id": fund_id, "amount": "500.00", "date": today},
    )
    return client.post(
        "/transactions/quick-add",
        json={
            "fund_id": fund_id,
            "amount": amount,
            "date": today,
            "merchant": merchant,
            "type": "expense",
        },
    ).json()


def test_move_retags_the_transaction_to_the_new_fund(client):
    groceries = _make_fund(client, "Groceries")
    dining = _make_fund(client, "Dining")
    txn = _assigned_expense(client, groceries, "40.00", "Trader Joe's")

    resp = client.post(f"/transactions/{txn['id']}/move", json={"fund_id": dining})

    assert resp.status_code == 200
    moved = resp.json()
    assert moved["id"] == txn["id"]
    assert moved["fund_id"] == dining


def test_move_refuses_an_invalid_destination_atomically(client):
    groceries = _make_fund(client, "Groceries")
    txn = _assigned_expense(client, groceries, "40.00", "Trader Joe's")

    missing_fund_id = 999_999
    resp = client.post(
        f"/transactions/{txn['id']}/move", json={"fund_id": missing_fund_id}
    )

    assert resp.status_code == 400
    # The row is untouched: it still belongs to the original fund.
    still = client.get(f"/transactions?fund_id={groceries}").json()
    assert txn["id"] in [t["id"] for t in still]


def test_move_preserves_the_fields_and_adds_no_row(client):
    groceries = _make_fund(client, "Groceries")
    dining = _make_fund(client, "Dining")
    txn = _assigned_expense(client, groceries, "40.00", "Trader Joe's")

    before = client.get("/transactions?limit=500").json()
    moved = client.post(
        f"/transactions/{txn['id']}/move", json={"fund_id": dining}
    ).json()
    after = client.get("/transactions?limit=500").json()

    # Same count — the existing row is updated, not duplicated.
    assert len(after) == len(before)
    # Amount, date and merchant ride along unchanged.
    assert moved["amount"] == txn["amount"]
    assert moved["date"] == txn["date"]
    assert moved["merchant"] == txn["merchant"]


def test_move_preserves_the_plaid_id(client):
    """A Plaid-imported expense keeps its plaid_transaction_id after the move."""
    from app.db import new_session
    from app.models import Transaction, TxType

    groceries = _make_fund(client, "Groceries")
    dining = _make_fund(client, "Dining")

    with new_session() as s:
        t = Transaction(
            fund_id=groceries,
            type=TxType.expense,
            amount=Decimal("-40.00"),
            date=date.today().replace(day=15),
            merchant="Trader Joe's",
            plaid_transaction_id="plaid-xyz-123",
        )
        s.add(t)
        s.commit()
        txn_id = t.id

    moved = client.post(
        f"/transactions/{txn_id}/move", json={"fund_id": dining}
    ).json()

    assert moved["fund_id"] == dining
    assert moved["plaid_transaction_id"] == "plaid-xyz-123"


def test_move_updates_both_fund_balances(client):
    groceries = _make_fund(client, "Groceries")  # 500 assigned, 40 spent -> 460
    dining = _make_fund(client, "Dining")         # 0
    txn = _assigned_expense(client, groceries, "40.00", "Trader Joe's")

    assert Decimal(client.get(f"/funds/{groceries}").json()["balance"]) == Decimal("460.00")
    assert Decimal(client.get(f"/funds/{dining}").json()["balance"]) == Decimal("0.00")

    client.post(f"/transactions/{txn['id']}/move", json={"fund_id": dining})

    # The expense left Groceries (balance climbs back) and landed on Dining.
    assert Decimal(client.get(f"/funds/{groceries}").json()["balance"]) == Decimal("500.00")
    assert Decimal(client.get(f"/funds/{dining}").json()["balance"]) == Decimal("-40.00")


def test_move_rejects_an_assignment_leg(client):
    """Assignment/transfer legs are double-entry and can't be single-sided moved."""
    groceries = _make_fund(client, "Groceries")
    dining = _make_fund(client, "Dining")
    today = date.today().replace(day=15).isoformat()
    client.post(
        "/transactions/assign",
        json={"fund_id": groceries, "amount": "500.00", "date": today},
    )
    # The assignment credit sitting on the fund.
    rows = client.get(f"/transactions?fund_id={groceries}").json()
    leg = next(t for t in rows if t["type"] == "assignment")

    resp = client.post(f"/transactions/{leg['id']}/move", json={"fund_id": dining})

    assert resp.status_code == 400


def test_move_404s_for_a_missing_transaction(client):
    dining = _make_fund(client, "Dining")
    resp = client.post("/transactions/999999/move", json={"fund_id": dining})
    assert resp.status_code == 404
