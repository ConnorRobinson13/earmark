"""The net-worth HTTP contract: what the page reads, and what writes history.

The response shape is load-bearing for the existing frontend, so it is asserted
key by key. The other half of this file is the split the router used to blur:
reading net worth is a read, and recording a snapshot is a separate, explicit
request.
"""
from __future__ import annotations

from decimal import Decimal


def _account(client, name: str, type_: str, balance: str) -> dict:
    r = client.post(
        "/accounts", json={"name": name, "type": type_, "current_balance": balance}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_networth_response_shape(client):
    _account(client, "Checking", "checking", "1500.00")
    _account(client, "Visa", "credit", "500.00")

    body = client.get("/networth").json()

    assert set(body) == {
        "total", "liquid", "investment", "emergency_fund",
        "credit_debt", "loan_debt", "by_type", "accounts",
    }
    assert body["total"] == "1000.00"
    assert body["liquid"] == "1500.00"
    assert body["credit_debt"] == "500.00"
    assert body["by_type"]["checking"] == "1500.00"
    assert [a["name"] for a in body["accounts"]] == ["Checking", "Visa"]
    assert set(body["accounts"][0]) == {
        "id", "name", "type", "balance", "last_synced_at",
    }
    assert body["accounts"][0]["balance"] == "1500.00"


def test_get_networth_does_not_write_a_snapshot(client):
    _account(client, "Checking", "checking", "1500.00")

    client.get("/networth")

    assert client.get("/networth/history").json() == []


def test_snapshot_endpoint_records_this_month(client):
    _account(client, "Checking", "checking", "1500.00")

    r = client.post("/networth/snapshot")
    assert r.status_code == 201, r.text
    assert Decimal(r.json()["total"]) == Decimal("1500.00")

    history = client.get("/networth/history").json()
    assert len(history) == 1
    assert history[0] == r.json()


def test_snapshotting_twice_updates_the_same_month(client):
    acct = _account(client, "Checking", "checking", "1500.00")
    client.post("/networth/snapshot")

    client.patch(f"/accounts/{acct['id']}", json={"current_balance": "1750.00"})
    client.post("/networth/snapshot")

    history = client.get("/networth/history").json()
    assert len(history) == 1
    assert Decimal(history[0]["total"]) == Decimal("1750.00")
