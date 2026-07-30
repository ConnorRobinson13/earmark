"""Planned income is a number of dollars you expect, not a signed adjustment.

Unassigned is computed from it, so a negative reads as money to budget that was
never earned. The web UI refuses one in its input handler; these pin the same rule
to the endpoint, which is the only place a second client — the MCP server — can
meet it.
"""
from __future__ import annotations

import pytest


def test_a_negative_planned_income_is_refused(client):
    resp = client.put("/monthly-meta/2026-07", json={"planned_income": "-4200"})

    assert resp.status_code == 422
    assert client.get("/monthly-meta/2026-07").json()["planned_income"] == "0"


@pytest.mark.parametrize("amount", ["0", "4200", "4200.55"])
def test_zero_and_up_are_accepted(client, amount):
    assert client.put(
        "/monthly-meta/2026-07", json={"planned_income": amount}
    ).status_code == 200


def test_a_refused_write_leaves_an_existing_figure_alone(client):
    client.put("/monthly-meta/2026-07", json={"planned_income": "4200"})

    client.put("/monthly-meta/2026-07", json={"planned_income": "-1"})

    assert client.get("/monthly-meta/2026-07").json()["planned_income"] == "4200.00"
