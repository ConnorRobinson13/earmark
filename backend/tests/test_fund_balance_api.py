"""End-to-end: a fund's balance over the HTTP layer.

Everything goes through the API — create the fund, assign money to it, spend
from it — and the balance the API reports back is the signed sum of what was
posted. This is the first test that exercises router → service → database as one
piece, so it is also the proof that the disposable-database seam works.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def test_fund_balance_is_assignments_minus_spending(client):
    today = date.today().replace(day=15).isoformat()

    fund_id = client.post("/funds", json={"name": "Groceries"}).json()["id"]

    assert client.post(
        "/transactions/assign",
        json={"fund_id": fund_id, "amount": "400.00", "date": today},
    ).status_code == 201
    assert client.post(
        "/transactions/quick-add",
        json={
            "fund_id": fund_id,
            "amount": "125.50",
            "date": today,
            "merchant": "Trader Joe's",
            "type": "expense",
        },
    ).status_code == 201

    fund = client.get(f"/funds/{fund_id}").json()
    assert Decimal(fund["balance"]) == Decimal("274.50")
    assert Decimal(fund["assigned_this_month"]) == Decimal("400.00")
    assert Decimal(fund["net_spent_this_month"]) == Decimal("125.50")


def test_new_fund_starts_at_zero(client):
    fund = client.post("/funds", json={"name": "Car Repairs"}).json()
    assert Decimal(fund["balance"]) == Decimal("0")

    listed = client.get("/funds").json()
    assert [f["name"] for f in listed] == ["Car Repairs"]
