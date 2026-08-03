"""End-to-end: the cash-flow endpoint's response body.

The arithmetic behind the plan is covered without a database in
`test_cashflow.py`. What is left to prove over HTTP is the wiring — that the
gather step reads the same funds, paydays and planned income the projection
expects — and the shape of the body itself.

That shape is a contract with the UI, which reads amounts as strings and renders
them as-is, so a balance arriving as the JSON number 1800.0 instead of the string
"1800.00" would be a visible bug rather than a formatting nicety.
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

TOP_LEVEL_KEYS = [
    "month",
    "past",
    "today",
    "start_balance",
    "ending_balance",
    "min_balance",
    "min_date",
    "goes_negative",
    "days",
]


def _seed(client) -> None:
    """A checking account, a payday, and a bill big enough to see land."""
    this_month = date.today().replace(day=1)
    client.post(
        "/accounts",
        json={"name": "Checking", "type": "checking", "current_balance": "2000.00"},
    )
    client.post("/paydays", json={"day_of_month": 15, "amount": "1500.00"})
    fund_id = client.post("/funds", json={"name": "Rent", "due_day": 20}).json()["id"]
    client.post(
        "/transactions/assign",
        json={
            "fund_id": fund_id,
            "amount": "1800.00",
            "date": this_month.isoformat(),
        },
    )


def test_the_body_keeps_the_shape_the_ui_reads(client):
    _seed(client)
    body = json.loads(client.get("/cashflow").text)

    assert list(body) == TOP_LEVEL_KEYS
    assert body["past"] is False
    assert body["month"] == date.today().replace(day=1).isoformat()
    assert body["today"] == date.today().isoformat()

    assert list(body["days"][0]) == ["date", "balance", "events", "is_today"]
    assert [d["date"] for d in body["days"]] == [
        date.today().replace(day=n).isoformat()
        for n in range(1, monthrange(date.today().year, date.today().month)[1] + 1)
    ]
    assert [d["is_today"] for d in body["days"]].count(True) == 1


def test_amounts_cross_the_wire_as_strings(client):
    _seed(client)
    body = json.loads(client.get("/cashflow").text)

    for key in ("start_balance", "ending_balance", "min_balance"):
        assert isinstance(body[key], str), key

    events = [e for day in body["days"] for e in day["events"]]
    assert [(e["kind"], e["label"], e["amount"]) for e in events] == [
        ("income", "Paycheck", "1500.00"),
        ("outflow", "Rent", "-1800.00"),
    ]
    for day in body["days"]:
        assert isinstance(day["balance"], str), day["date"]


def test_the_projection_reads_the_funds_and_paydays_that_were_posted(client):
    _seed(client)
    body = client.get("/cashflow").json()

    day = {d["date"]: d for d in body["days"]}
    first = date.today().replace(day=1)
    # Nothing lands before the 15th, so every day up to it sits on the anchor.
    assert Decimal(day[first.isoformat()]["balance"]) == Decimal(body["start_balance"])
    assert Decimal(day[first.replace(day=20).isoformat()]["balance"]) == Decimal(
        day[first.replace(day=15).isoformat()]["balance"]
    ) - Decimal("1800.00")


def test_a_month_already_over_reports_only_todays_cash(client):
    _seed(client)
    last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
    body = json.loads(client.get(f"/cashflow?month={last_month:%Y-%m}").text)

    assert list(body) == TOP_LEVEL_KEYS
    assert body == {
        "month": last_month.isoformat(),
        "past": True,
        "today": date.today().isoformat(),
        "start_balance": "2000.00",
        "ending_balance": "2000.00",
        "min_balance": "2000.00",
        "min_date": date.today().isoformat(),
        "goes_negative": False,
        "days": [],
    }
