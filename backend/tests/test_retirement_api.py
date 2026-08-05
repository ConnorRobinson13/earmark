"""The projection endpoint: what the web app and the MCP tool both call.

The recurrence itself is covered in `test_retirement.py` without a database.
What is left for here is the part that needs one — where the starting balance
comes from — plus the shape of the body, which two clients now chart from.
"""
from __future__ import annotations

from decimal import Decimal

#: The exact parameters both clients send for one shared set of assumptions.
#: `mcp/tests/test_server.py` and `frontend/src/views/NetWorth.test.jsx` pin the
#: same set from their own side; this asserts what the backend makes of it, so
#: the three together say the two clients get the same number for the same
#: question. Keep them in step.
SHARED_PARAMS = {
    "current_age": 28,
    "retire_age": 65,
    "annual_return_pct": 8,
    "monthly_contribution": 583,
    "contribution_growth_pct": 3,
    "inflation_pct": 2.5,
}


def _account(client, name: str, type_: str, balance: str) -> dict:
    r = client.post(
        "/accounts", json={"name": name, "type": type_, "current_balance": balance}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_the_projection_starts_from_the_investment_total(client):
    _account(client, "Vanguard", "investment", "30000.00")
    _account(client, "Fidelity", "investment", "12000.00")
    # Neither of these is an investment, so neither compounds toward retirement.
    _account(client, "Checking", "checking", "5000.00")
    _account(client, "Visa", "credit", "400.00")

    body = client.get(
        "/retirement/projection",
        params={"current_age": 40, "retire_age": 40},
    ).json()

    assert body["starting_balance"] == "42000.00"
    assert body["final_nominal"] == "42000.00"


def test_an_empty_ledger_projects_from_nothing(client):
    body = client.get(
        "/retirement/projection",
        params={"current_age": 30, "retire_age": 31, "monthly_contribution": "100"},
    ).json()

    assert body["starting_balance"] == "0.00"
    assert body["final_nominal"] == "1200.00"


def test_response_shape(client):
    _account(client, "Vanguard", "investment", "42000.00")

    body = client.get("/retirement/projection", params=SHARED_PARAMS).json()

    assert set(body) == {
        "current_age", "retire_age", "years",
        "annual_return_pct", "monthly_contribution",
        "contribution_growth_pct", "inflation_pct",
        "starting_balance", "total_contributed", "compounded_growth",
        "final_nominal", "final_real", "series",
    }
    assert body["years"] == 37
    assert len(body["series"]) == 38  # today, then one point per year
    assert set(body["series"][0]) == {"year", "age", "nominal", "real", "contributed"}
    assert body["series"][0] == {
        "year": 0, "age": 28,
        "nominal": "42000.00", "real": "42000.00", "contributed": "0.00",
    }
    assert body["series"][-1]["age"] == 65

    # Money crosses the wire as strings, so no client rounds a Decimal into a float.
    assert isinstance(body["final_nominal"], str)
    # The parameters come back so a chart can label itself without re-stating them.
    assert body["annual_return_pct"] == "8"
    assert body["inflation_pct"] == "2.5"


def test_the_headline_figures_add_up(client):
    _account(client, "Vanguard", "investment", "42000.00")

    body = client.get("/retirement/projection", params=SHARED_PARAMS).json()

    assert (
        Decimal(body["starting_balance"])
        + Decimal(body["total_contributed"])
        + Decimal(body["compounded_growth"])
        == Decimal(body["final_nominal"])
    )
    # Escalation and deflation are both on, so both are visible in the totals:
    # more went in than 583 × 12 × 37, and today's dollars are worth less.
    assert Decimal(body["total_contributed"]) > Decimal("583") * 12 * 37
    assert Decimal(body["final_real"]) < Decimal(body["final_nominal"])


def test_the_defaults_are_the_plain_recurrence(client):
    _account(client, "Vanguard", "investment", "1000.00")

    body = client.get(
        "/retirement/projection",
        params={"current_age": 30, "retire_age": 31, "annual_return_pct": "10"},
    ).json()

    # Nothing contributed, nothing escalating, nothing deflating.
    assert body["final_nominal"] == "1100.00"
    assert body["final_real"] == "1100.00"
    assert body["total_contributed"] == "0.00"


def test_the_projection_writes_nothing(client):
    _account(client, "Vanguard", "investment", "42000.00")

    client.get("/retirement/projection", params=SHARED_PARAMS)

    assert client.get("/networth/history").json() == []


def test_an_impossible_assumption_is_a_422(client):
    r = client.get(
        "/retirement/projection",
        params={"current_age": 30, "retire_age": 65, "monthly_contribution": "-500"},
    )

    assert r.status_code == 422, r.text
