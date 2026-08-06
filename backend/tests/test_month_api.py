"""Every endpoint that takes a month agrees on what a month is.

The parse block used to be copy-pasted per router with three different error
behaviours, so these tests are written against *all* the month-taking endpoints
at once: one rejection shape, both input forms accepted everywhere, and the same
answer whether the caller names the month or a day inside it.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.month import INVALID_MONTH_DETAIL

# name -> (method, url template, json body template). `{month}` is substituted
# with the month under test; `{fund_id}` with a fund created for the request.
MONTH_ENDPOINTS = {
    "dashboard": ("GET", "/dashboard?month={month}", None),
    "cashflow": ("GET", "/cashflow?month={month}", None),
    "settlements-pending": ("GET", "/settlements/pending?month={month}", None),
    "monthly-meta-get": ("GET", "/monthly-meta/{month}", None),
    "monthly-meta-put": ("PUT", "/monthly-meta/{month}", {"planned_income": "100"}),
    "copy-assignments-from": (
        "POST",
        "/bulk/copy-assignments",
        {"from_month": "{month}", "to_month": "2026-07-01"},
    ),
    "copy-assignments-to": (
        "POST",
        "/bulk/copy-assignments",
        {"from_month": "2026-07-01", "to_month": "{month}"},
    ),
    "set-monthly-income": (
        "POST",
        "/bulk/set-monthly-income",
        {"month": "{month}", "amount": "1000"},
    ),
    "archive-fund": ("DELETE", "/funds/{fund_id}?month={month}", None),
}

ENDPOINTS = sorted(MONTH_ENDPOINTS)

UNREADABLE_MONTHS = [
    "not-a-month",
    "2026-02-30",  # well-formed, but February has no 30th
    "2026-13",
    "20260715",  # compact ISO — `date.fromisoformat` takes it, a month does not
]


@pytest.fixture()
def send(client):
    """Call a month-taking endpoint with `month`, creating whatever it needs."""

    def _send(name: str, month: str):
        method, url, body = MONTH_ENDPOINTS[name]
        if "{fund_id}" in url:
            fund_id = client.post("/funds", json={"name": f"Fund {name} {month}"}).json()["id"]
            url = url.replace("{fund_id}", str(fund_id))
        if body is not None:
            body = {k: v.replace("{month}", month) for k, v in body.items()}
        return client.request(method, url.replace("{month}", month), json=body)

    return _send


@pytest.mark.parametrize("name", ENDPOINTS)
@pytest.mark.parametrize("month", UNREADABLE_MONTHS)
def test_an_unreadable_month_is_one_400_shape_everywhere(send, name, month):
    resp = send(name, month)
    assert resp.status_code == 400
    assert resp.json() == {"detail": INVALID_MONTH_DETAIL}


@pytest.mark.parametrize("name", ENDPOINTS)
@pytest.mark.parametrize("month", ["2026-07", "2026-07-01", "2026-07-15"])
def test_both_input_forms_are_accepted_everywhere(send, name, month):
    assert send(name, month).status_code < 400


def test_a_mid_month_day_reads_the_same_month_as_its_first(client):
    client.put("/monthly-meta/2026-07-01", json={"planned_income": "4200"})

    for month in ("2026-07", "2026-07-01", "2026-07-15", "2026-07-31"):
        assert client.get(f"/monthly-meta/{month}").json() == {
            "month": "2026-07-01",
            "planned_income": "4200.00",
        }


def test_writing_a_mid_month_day_lands_on_the_first(client):
    assert client.put(
        "/monthly-meta/2026-07-22", json={"planned_income": "500"}
    ).json()["month"] == "2026-07-01"

    listed = client.get("/monthly-meta").json()
    assert [row["month"] for row in listed] == ["2026-07-01"]


def test_the_dashboard_reports_the_first_of_whatever_month_it_was_asked_for(client):
    for month in ("2026-07", "2026-07-15"):
        assert client.get(f"/dashboard?month={month}").json()["month"] == "2026-07-01"


def test_an_absent_month_still_means_the_current_one(client):
    this_month = date.today().replace(day=1).isoformat()
    assert client.get("/dashboard").json()["month"] == this_month
    assert client.get("/cashflow").json()["month"] == this_month
