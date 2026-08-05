"""The tools forward what they were given.

Every defect these tests pin down had the same shape: the MCP layer re-deriving
something the backend already owns — what a month is, what sign an amount has,
whether a filter was supplied — and getting a different answer. So the
assertions are about the request that reaches the backend, and about the
docstrings, which are the whole interface as far as the model is concerned.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import server

BACKEND_MONTH = Path(__file__).resolve().parents[2] / "backend" / "app" / "month.py"
BACKEND_MODELS = Path(__file__).resolve().parents[2] / "backend" / "app" / "models.py"

# A month that will never be the current one, so the "some other month" branch
# stays that branch as time passes.
PAST_MONTH_FORMS = ["2020-03", "2020-03-01", "2020-03-17"]


def this_month_forms() -> list[str]:
    today = date.today()
    return [f"{today:%Y-%m}", f"{today:%Y-%m}-01", today.isoformat()]


def doc(tool) -> str:
    """A tool's docstring on one line — the description the model reads.

    Collapsing the whitespace means a phrase can be asserted on without the
    assertion also pinning down where the source happens to wrap.
    """
    return " ".join((tool.__doc__ or "").split())


# ─────────────────────── assign: month → transaction date ───────────────────────

@pytest.mark.parametrize("month", PAST_MONTH_FORMS)
def test_assigning_to_another_month_dates_the_assignment_to_that_month(api, month):
    """Both wire forms of a month land on its first day.

    The bug: the short `YYYY-MM` form — which every month-taking endpoint
    accepts — failed a string comparison against a locally built `YYYY-MM-01`
    and was posted verbatim as a transaction date.
    """
    server.assign_to_fund(fund_id=4, amount=125.0, month=month)

    assert api.body["date"] == "2020-03-01"


@pytest.mark.parametrize("month", this_month_forms())
def test_assigning_inside_the_current_month_dates_the_assignment_to_today(api, month):
    server.assign_to_fund(fund_id=4, amount=125.0, month=month)

    assert api.body["date"] == date.today().isoformat()


def test_assigning_with_no_month_dates_the_assignment_to_today(api):
    server.assign_to_fund(fund_id=4, amount=125.0)

    assert api.request.url.path == "/transactions/assign"
    assert api.body["date"] == date.today().isoformat()


def test_one_assignment_reads_the_clock_once(api, monkeypatch):
    """Every "now" in a single assignment comes from one reading of the clock.

    Today and the current month were sampled separately — three `date.today()`
    calls across two lines — so a call that straddles midnight on the first of a
    month compared June's month against July's and fell to the "some other
    month" branch, dating a *current*-month assignment to a day that had already
    passed. Rare, and silent when it happens: the posted date is a real date, it
    just isn't the one asked for.
    """
    ticks = iter([date(2020, 6, 30), date(2020, 7, 1), date(2020, 7, 1)])

    class TickingDate(date):
        @classmethod
        def today(cls) -> date:
            return next(ticks)

    monkeypatch.setattr(server, "date", TickingDate)

    server.assign_to_fund(fund_id=4, amount=125.0)

    assert api.body["date"] == "2020-06-30"


@pytest.mark.parametrize(
    "month",
    [
        "not-a-month",
        "2026-02-30",  # well-formed, but February has no 30th
        "2026-13",
        "20260715",  # compact ISO — `date.fromisoformat` takes it, a month does not
        "2026-07-01T00:00:00",
    ],
)
def test_a_month_the_backend_could_not_read_is_refused_before_anything_is_posted(api, month):
    """An unreadable month is a bad request, not a bad transaction date.

    `/transactions/assign` takes a date, so it cannot police a month for us —
    and it would happily accept a plausible-but-wrong date derived from one.
    """
    with pytest.raises(ValueError, match="month must be YYYY-MM or YYYY-MM-DD"):
        server.assign_to_fund(fund_id=4, amount=125.0, month=month)

    assert api.requests == []


# ─────────────────────────── amounts keep their sign ───────────────────────────

def test_pulling_money_back_out_of_a_fund_stays_negative(api):
    server.assign_to_fund(fund_id=4, amount=-40.0, month="2020-03")

    assert api.body["amount"] == -40.0


def test_a_negative_expense_is_forwarded_not_flipped(api):
    """`abs()` here turned "you got the sign wrong" into a silent, wrong write."""
    server.record_transaction(fund_id=4, amount=-12.5, merchant="Blue Bottle")

    assert api.body["amount"] == -12.5


def test_a_negative_settlement_is_forwarded_not_flipped(api):
    server.mark_goal_contributed(goal_id=7, amount=-500.0)

    assert api.body["amount"] == -500.0


def test_a_negative_planned_income_is_forwarded_not_flipped(api):
    """Forwarded so the backend can refuse it — `Field(ge=0)` on
    `MonthlyMetaPatch` is what makes that refusal happen, and
    `backend/tests/test_monthly_meta_api.py` is what holds it there."""
    server.set_planned_income(month="2026-07", amount=-4200.0)

    assert api.request.url.path == "/monthly-meta/2026-07"
    assert api.body["planned_income"] == -4200.0


# ───────────────────── the backend's own errors reach the caller ─────────────────

def test_a_rejected_amount_reports_what_the_backend_said(api):
    """A tool error is the only channel back, so the body travels with the status."""
    api.replies(400, {"detail": "amount must be positive"})

    with pytest.raises(server.BudgetApiError, match="amount must be positive") as exc:
        server.mark_goal_contributed(goal_id=7, amount=-500.0)

    assert "400" in str(exc.value)


def test_a_validation_failure_reports_the_field_that_failed(api):
    api.replies(422, {"detail": [{"loc": ["body", "amount"], "msg": "Input should be greater than 0"}]})

    with pytest.raises(server.BudgetApiError, match="Input should be greater than 0"):
        server.record_transaction(fund_id=4, amount=-12.5)


def test_an_error_with_no_json_body_still_reports_its_status(api):
    api.replies(502, None)

    with pytest.raises(server.BudgetApiError, match="502"):
        server.financial_overview()


# ──────────────────────────── search: filter presence ────────────────────────────

def test_an_explicit_zero_bound_reaches_the_backend(api):
    """`max_amount=0` narrows the search to nothing-but-zero-amount rows.

    Testing truthiness dropped it, which silently returned *everything* — the
    opposite of what was asked.
    """
    server.search_transactions(max_amount=0)

    assert api.params["max_amount"] == "0"


def test_a_zero_lower_bound_reaches_the_backend(api):
    server.search_transactions(min_amount=0)

    assert api.params["min_amount"] == "0"


def test_filters_that_were_not_supplied_are_left_out(api):
    server.search_transactions()

    assert api.request.url.path == "/transactions/search"
    assert dict(api.params) == {}


def test_supplied_filters_are_forwarded_as_given(api):
    server.search_transactions(
        start="2026-01-01",
        end="2026-03-31",
        merchant="coffee",
        fund_id=4,
        type="expense",
        min_amount=5,
        max_amount=50,
    )

    assert dict(api.params) == {
        "start": "2026-01-01",
        "end": "2026-03-31",
        "merchant": "coffee",
        "fund_id": "4",
        "type": "expense",
        "min_amount": "5",
        "max_amount": "50",
    }


# ───────────────────── the retirement projection is the backend's ─────────────────

BACKEND_PROJECTION_TEST = (
    Path(__file__).resolve().parents[2] / "backend" / "tests" / "test_retirement_api.py"
)

#: The exact parameters this tool sends for one shared set of assumptions.
#: `frontend/src/views/NetWorth.test.jsx` pins the same set from the web app's
#: side and `backend/tests/test_retirement_api.py` pins what the backend makes
#: of it — between them, the two clients get the same answer to the same
#: question, which is the whole reason the recurrence moved to the backend.
#: The three copies are held together by the drift test below, the same way
#: `INVALID_MONTH_DETAIL` is: this container ships without the backend on its
#: path, so agreement has to be asserted rather than imported.
SHARED_PARAMS = {
    "current_age": 28,
    "retire_age": 65,
    "annual_return_pct": 8,
    "monthly_contribution": 583,
    "contribution_growth_pct": 3,
    "inflation_pct": 2.5,
}


def test_the_projection_is_asked_for_rather_than_worked_out(api):
    """The tool compounded its own series, and its copy of the recurrence had
    drifted from the web app's — no escalation, no inflation. Now there is one
    copy, behind one endpoint, and this tool forwards to it."""
    server.project_retirement(**SHARED_PARAMS)

    assert api.request.url.path == "/retirement/projection"
    assert {k: float(v) for k, v in api.params.items()} == {
        k: float(v) for k, v in SHARED_PARAMS.items()
    }


def test_the_projection_comes_back_untouched(api):
    """Reshaping the body here would be the same mistake in a smaller place:
    the model would read numbers the page never shows."""
    body = {
        "years": 1,
        "starting_balance": "42000.00",
        "final_nominal": "46943.00",
        "final_real": "45798.05",
        "series": [{"year": 0, "age": 28, "nominal": "42000.00", "real": "42000.00", "contributed": "0.00"}],
    }
    api.replies(200, body)

    assert server.project_retirement(current_age=28, retire_age=29) == body


def test_the_projection_defaults_still_reach_the_backend(api):
    """Every dial is sent, defaults included, so the backend's answer depends on
    nothing this container decided to leave out."""
    server.project_retirement(current_age=30, retire_age=65)

    assert dict(api.params) == {
        "current_age": "30",
        "retire_age": "65",
        "annual_return_pct": "8.0",
        "monthly_contribution": "0.0",
        "contribution_growth_pct": "0.0",
        "inflation_pct": "0.0",
    }


def test_the_shared_projection_parameters_have_not_drifted():
    """The set above is the one the backend and the web app pin too.

    "Both clients get the same answer" is only worth asserting while the three
    suites are asking the same question, and nothing else would notice if one
    of them quietly started asking a different one.
    """
    if not BACKEND_PROJECTION_TEST.exists():  # running from the container
        pytest.skip(f"{BACKEND_PROJECTION_TEST} is not in this checkout")

    source = BACKEND_PROJECTION_TEST.read_text()
    for name, value in SHARED_PARAMS.items():
        assert f'"{name}": {value},' in source


def test_the_projection_reads_no_other_endpoint(api):
    """It used to fetch /networth for the starting balance and compound from
    there. The starting balance is the endpoint's business now."""
    server.project_retirement(current_age=30, retire_age=65)

    assert [r.url.path for r in api.requests] == ["/retirement/projection"]


# ─────────────────────── operational funds vs goals ───────────────────────

# One fund list, cut two ways by the two tools below.
BOTH_KINDS = [
    {"id": 1, "name": "Groceries", "kind": "operational"},
    {"id": 2, "name": "Emergency fund", "kind": "goal"},
    {"id": 3, "name": "Rent", "kind": "operational"},
]


def test_list_funds_reports_the_operational_half(api):
    api.replies(200, {"funds": BOTH_KINDS})

    assert server.list_funds() == [BOTH_KINDS[0], BOTH_KINDS[2]]


def test_list_goals_reports_the_goal_half(api):
    api.replies(200, BOTH_KINDS)

    assert server.list_goals() == [BOTH_KINDS[1]]


def test_a_kind_neither_tool_knows_is_listed_by_neither(api):
    """Both cuts ask what a fund is, not what it is not — so an unrecognised
    kind falls out of both lists rather than into whichever one was written as
    "not the other", where the model would read it under a heading that is wrong
    and nothing would error. Nothing is broken here today; this pins which of
    the two spellings stays."""
    unknown = {"id": 4, "name": "Sinking fund", "kind": "sinking"}

    api.replies(200, {"funds": [*BOTH_KINDS, unknown]})
    assert unknown not in server.list_funds()

    api.replies(200, [*BOTH_KINDS, unknown])
    assert unknown not in server.list_goals()


def test_the_fund_kinds_are_the_backend_s_word_for_word():
    """`OPERATIONAL_KIND`/`GOAL_KIND` are copied, not imported — this container
    has no backend on its path — so the copies are held to `FundKind`, the same
    way the bad-month message is held to the backend's."""
    if not BACKEND_MODELS.exists():  # running from the container, where it isn't
        pytest.skip(f"{BACKEND_MODELS} is not in this checkout")

    source = BACKEND_MODELS.read_text()
    assert f'operational = "{server.OPERATIONAL_KIND}"' in source
    assert f'goal = "{server.GOAL_KIND}"' in source


# ────────────────────────────── docstrings don't lie ──────────────────────────────

def test_the_search_docstring_does_not_promise_signed_amount_filtering():
    """The endpoint filters on `abs(amount)`; the docstring used to say the
    bounds were signed, so the model would ask for `-20..0` to find spending."""
    assert "ignores sign" in doc(server.search_transactions)
    assert "negative is money out" not in doc(server.search_transactions)


def test_the_bad_month_message_is_the_backend_s_word_for_word():
    """`INVALID_MONTH_DETAIL` is copied, not imported — this container has no
    backend on its path — so the copy has to be held to the original."""
    if not BACKEND_MONTH.exists():  # running from the container, where it isn't
        pytest.skip(f"{BACKEND_MONTH} is not in this checkout")

    declared = f'INVALID_MONTH_DETAIL = "{server.INVALID_MONTH_DETAIL}"'
    assert declared in BACKEND_MONTH.read_text()


def test_the_projection_docstring_describes_the_body_the_backend_sends():
    """It used to describe a body this tool built itself — a `final_value` and a
    `series` of `value`s, none of which exist any more."""
    described = doc(server.project_retirement)
    assert "final_nominal" in described and "final_real" in described
    assert "`nominal` is future dollars" in described
    assert "final_value" not in described


def test_the_two_fund_listing_tools_say_which_month_they_report():
    """`list_funds` is month-scoped and `list_goals` can't be — /funds has no
    month. Whichever way that lands, the docstrings have to say so."""
    assert "Empty = current month" in doc(server.list_funds)
    assert "Current month only" in doc(server.list_goals)
