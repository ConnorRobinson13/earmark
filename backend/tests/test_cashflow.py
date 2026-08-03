"""The cash-flow projection, exercised without a database.

Every case here hands `project` a `CashflowInputs` built by literal and reads the
plan back. That is the point of the split: the payday even-split, the back-solve
that anchors the running balance to today's real cash, and the day walk are
arithmetic, and arithmetic does not need Postgres.

`today` is an input rather than a clock read, so the expectations below are
calendar literals that cannot go stale. July 2026 (31 days) is the working month
throughout; February 2026 (28 days) appears where day-of-month clamping matters.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.cashflow import (
    CashflowDay,
    CashflowInputs,
    CashflowPlan,
    FundCharge,
    MonthInputs,
    Payday,
    project,
)

JULY = date(2026, 7, 1)
MID_JULY = date(2026, 7, 15)
AUGUST = date(2026, 8, 1)


# ---------- builders ----------

def payday(day: int, amount: str | None = None) -> Payday:
    """A payday. No amount means "take an even share of planned income"."""
    return Payday(day_of_month=day, amount=None if amount is None else Decimal(amount))


def bill(name: str, day: int, assigned: str) -> FundCharge:
    return FundCharge(name=name, due_day=day, assigned=Decimal(assigned))


def month_of(
    month: date, planned_income: str = "0", funds: Sequence[FundCharge] = ()
) -> MonthInputs:
    return MonthInputs(
        month=month, planned_income=Decimal(planned_income), funds=list(funds)
    )


def inputs(
    *,
    today: date = MID_JULY,
    month: date = JULY,
    liquid_cash: str = "1000",
    paydays: Sequence[Payday] = (),
    months: Sequence[MonthInputs] = (),
) -> CashflowInputs:
    return CashflowInputs(
        today=today,
        month=month,
        liquid_cash=Decimal(liquid_cash),
        paydays=list(paydays),
        months=list(months),
    )


def day_on(plan: CashflowPlan, d: date) -> CashflowDay:
    return next(day for day in plan.days if day.date == d)


# ---------- the payday split ----------

def test_a_lone_open_ended_payday_takes_the_whole_planned_income():
    plan = project(
        inputs(paydays=[payday(10)], months=[month_of(JULY, planned_income="3000")])
    )
    assert [e.amount for e in day_on(plan, date(2026, 7, 10)).events] == [Decimal("3000")]


def test_two_open_ended_paydays_split_the_planned_income_evenly():
    plan = project(
        inputs(
            paydays=[payday(1), payday(15)],
            months=[month_of(JULY, planned_income="3000")],
        )
    )
    assert day_on(plan, date(2026, 7, 1)).events[0].amount == Decimal("1500")
    assert day_on(plan, date(2026, 7, 15)).events[0].amount == Decimal("1500")


def test_a_fixed_payday_comes_off_the_top_before_the_rest_is_split():
    plan = project(
        inputs(
            paydays=[payday(1, "1000"), payday(15), payday(25)],
            months=[month_of(JULY, planned_income="3000")],
        )
    )
    assert day_on(plan, date(2026, 7, 1)).events[0].amount == Decimal("1000")
    assert day_on(plan, date(2026, 7, 15)).events[0].amount == Decimal("1000")
    assert day_on(plan, date(2026, 7, 25)).events[0].amount == Decimal("1000")


def test_a_split_that_does_not_divide_evenly_keeps_its_full_precision():
    plan = project(
        inputs(
            paydays=[payday(1), payday(11), payday(21)],
            months=[month_of(JULY, planned_income="2500")],
        )
    )
    assert day_on(plan, date(2026, 7, 1)).events[0].amount == Decimal("2500") / 3


def test_fixed_paydays_alone_leave_the_rest_of_planned_income_unpaid():
    # Nothing to split across, so the remaining 2000 has no payday to land on.
    plan = project(
        inputs(
            paydays=[payday(1, "1000")],
            months=[month_of(JULY, planned_income="3000")],
        )
    )
    assert [e.amount for day in plan.days for e in day.events] == [Decimal("1000")]


def test_a_payday_with_nothing_to_deposit_is_left_off_the_day():
    plan = project(
        inputs(paydays=[payday(10)], months=[month_of(JULY, planned_income="0")])
    )
    assert day_on(plan, date(2026, 7, 10)).events == []


def test_a_payday_can_land_a_negative_deposit_when_the_fixed_ones_overshoot():
    # Planned income already spoken for twice over: the open-ended payday is
    # what absorbs the shortfall, rather than the split silently flooring at 0.
    plan = project(
        inputs(
            paydays=[payday(1, "3000"), payday(15)],
            months=[month_of(JULY, planned_income="2000")],
        )
    )
    assert day_on(plan, date(2026, 7, 15)).events[0].amount == Decimal("-1000")


def test_a_payday_on_the_31st_lands_on_the_last_day_of_a_short_month():
    plan = project(
        inputs(
            today=date(2026, 2, 10),
            month=date(2026, 2, 1),
            paydays=[payday(31)],
            months=[month_of(date(2026, 2, 1), planned_income="3000")],
        )
    )
    assert day_on(plan, date(2026, 2, 28)).events[0].amount == Decimal("3000")


# ---------- bills ----------

def test_a_funds_whole_assignment_leaves_the_account_on_its_due_day():
    plan = project(
        inputs(months=[month_of(JULY, funds=[bill("Rent", 20, "1800")])])
    )
    event = day_on(plan, date(2026, 7, 20)).events[0]
    assert (event.kind, event.label, event.amount) == ("outflow", "Rent", Decimal("-1800"))


def test_a_fund_with_nothing_assigned_never_shows_up():
    plan = project(inputs(months=[month_of(JULY, funds=[bill("Rent", 20, "0")])]))
    assert [e for day in plan.days for e in day.events] == []


def test_a_bill_due_on_the_31st_lands_on_the_last_day_of_a_short_month():
    plan = project(
        inputs(
            today=date(2026, 2, 10),
            month=date(2026, 2, 1),
            months=[month_of(date(2026, 2, 1), funds=[bill("Rent", 31, "1800")])],
        )
    )
    assert day_on(plan, date(2026, 2, 28)).events[0].label == "Rent"


def test_paychecks_come_before_bills_on_a_day_they_share():
    plan = project(
        inputs(
            paydays=[payday(20)],
            months=[
                month_of(JULY, planned_income="3000", funds=[bill("Rent", 20, "1800")])
            ],
        )
    )
    assert [e.kind for e in day_on(plan, date(2026, 7, 20)).events] == ["income", "outflow"]


# ---------- the anchor back-solve ----------

def test_todays_balance_is_exactly_the_cash_in_the_account_now():
    plan = project(
        inputs(
            liquid_cash="1234.56",
            paydays=[payday(1, "2000")],
            months=[month_of(JULY, funds=[bill("Rent", 5, "1800")])],
        )
    )
    assert day_on(plan, MID_JULY).balance == Decimal("1234.56")


def test_events_already_past_are_solved_backwards_out_of_todays_cash():
    # A 2000 paycheck landed on the 1st and today's balance is 1000, so the
    # month can only have opened at -1000. The projection says so rather than
    # pretending the month started where the account did.
    plan = project(
        inputs(
            liquid_cash="1000",
            paydays=[payday(1, "2000")],
            months=[month_of(JULY)],
        )
    )
    assert plan.start_balance == Decimal("-1000")
    assert day_on(plan, date(2026, 7, 1)).balance == Decimal("1000")
    assert day_on(plan, MID_JULY).balance == Decimal("1000")


def test_events_still_to_come_do_not_move_the_anchor():
    plan = project(
        inputs(
            liquid_cash="1000",
            paydays=[payday(25, "2000")],
            months=[month_of(JULY)],
        )
    )
    assert plan.start_balance == Decimal("1000")
    assert day_on(plan, MID_JULY).balance == Decimal("1000")
    assert day_on(plan, date(2026, 7, 25)).balance == Decimal("3000")


def test_an_event_dated_today_counts_as_already_landed():
    # Today's balance is the real one, so an event dated today is part of it.
    plan = project(
        inputs(
            liquid_cash="1000",
            paydays=[payday(15, "2000")],
            months=[month_of(JULY)],
        )
    )
    assert day_on(plan, MID_JULY).balance == Decimal("1000")
    assert day_on(plan, date(2026, 7, 14)).balance == Decimal("-1000")


def test_a_later_month_is_anchored_through_the_months_in_between():
    # Selected August while standing in July: the August days have to carry
    # July's remaining paycheck forward, or the month would open at today's cash.
    plan = project(
        inputs(
            month=AUGUST,
            liquid_cash="500",
            paydays=[payday(1, "1000")],
            months=[month_of(JULY), month_of(AUGUST)],
        )
    )
    assert plan.start_balance == Decimal("500")
    assert day_on(plan, AUGUST).balance == Decimal("1500")
    assert plan.days[0].date == AUGUST
    assert plan.ending_balance == Decimal("1500")


# ---------- the goes-negative flag ----------

def test_a_bill_that_outruns_the_balance_trips_the_negative_flag():
    plan = project(
        inputs(liquid_cash="100", months=[month_of(JULY, funds=[bill("Rent", 20, "500")])])
    )
    assert plan.goes_negative is True
    assert plan.min_balance == Decimal("-400")


def test_a_month_that_only_reaches_zero_does_not_count_as_negative():
    plan = project(
        inputs(liquid_cash="500", months=[month_of(JULY, funds=[bill("Rent", 20, "500")])])
    )
    assert plan.goes_negative is False
    assert plan.min_balance == Decimal("0")


def test_a_month_that_never_dips_is_not_negative():
    plan = project(inputs(liquid_cash="1000", months=[month_of(JULY)]))
    assert plan.goes_negative is False


# ---------- the minimum-balance day ----------

def test_the_minimum_is_the_lowest_closing_balance_of_the_month():
    plan = project(
        inputs(
            liquid_cash="1000",
            paydays=[payday(25, "900")],
            months=[month_of(JULY, funds=[bill("Rent", 20, "800")])],
        )
    )
    assert plan.min_balance == Decimal("200")
    assert plan.min_date == date(2026, 7, 20)


def test_the_minimum_is_the_first_day_that_reaches_it():
    # The balance drops to 100 on the 10th, climbs on the 20th, and comes back
    # to 100 on the 25th. The day worth warning about is the first one.
    plan = project(
        inputs(
            liquid_cash="100",
            paydays=[payday(20, "50")],
            months=[
                month_of(
                    JULY,
                    funds=[bill("Rent", 10, "50"), bill("Power", 25, "50")],
                )
            ],
        )
    )
    assert plan.min_balance == Decimal("100")
    assert plan.min_date == date(2026, 7, 10)


def test_the_minimum_of_a_flat_month_is_its_first_day():
    plan = project(inputs(liquid_cash="1000", months=[month_of(JULY)]))
    assert plan.min_balance == Decimal("1000")
    assert plan.min_date == JULY


# ---------- the past-month short circuit ----------

def test_a_month_already_over_reports_only_todays_cash():
    plan = project(
        inputs(
            today=MID_JULY,
            month=date(2026, 6, 1),
            liquid_cash="1234.56",
            paydays=[payday(1, "2000")],
            months=[month_of(date(2026, 6, 1), planned_income="3000")],
        )
    )
    assert plan.past is True
    assert plan.days == []
    assert plan.month == date(2026, 6, 1)
    assert plan.today == MID_JULY
    assert plan.start_balance == Decimal("1234.56")
    assert plan.ending_balance == Decimal("1234.56")
    assert plan.min_balance == Decimal("1234.56")
    assert plan.min_date == MID_JULY


def test_a_past_month_is_never_flagged_negative_even_when_cash_is():
    # Pinning the long-standing contract rather than endorsing it: the past
    # branch reports `goes_negative` false whatever the balance is, because
    # there is no projected day for it to describe.
    plan = project(inputs(today=MID_JULY, month=date(2026, 6, 1), liquid_cash="-50"))
    assert plan.goes_negative is False


def test_the_month_that_ends_today_is_still_projected():
    plan = project(inputs(today=date(2026, 7, 31), months=[month_of(JULY)]))
    assert plan.past is False
    assert len(plan.days) == 31


def test_the_month_that_ended_yesterday_is_past():
    plan = project(inputs(today=date(2026, 7, 1), month=date(2026, 6, 1)))
    assert plan.past is True


# ---------- the day walk ----------

def test_there_is_one_entry_for_every_day_of_the_month():
    plan = project(inputs(months=[month_of(JULY)]))
    assert [day.date for day in plan.days] == [date(2026, 7, d) for d in range(1, 32)]


def test_a_short_month_gets_only_the_days_it_has():
    plan = project(
        inputs(
            today=date(2026, 2, 10),
            month=date(2026, 2, 1),
            months=[month_of(date(2026, 2, 1))],
        )
    )
    assert len(plan.days) == 28


def test_only_todays_entry_is_flagged_as_today():
    plan = project(inputs(months=[month_of(JULY)]))
    assert [day.date for day in plan.days if day.is_today] == [MID_JULY]


def test_no_day_is_flagged_as_today_in_a_month_that_is_not_this_one():
    plan = project(inputs(month=AUGUST, months=[month_of(JULY), month_of(AUGUST)]))
    assert not any(day.is_today for day in plan.days)


def test_the_ending_balance_is_the_last_days_balance():
    plan = project(
        inputs(liquid_cash="1000", months=[month_of(JULY, funds=[bill("Rent", 20, "300")])])
    )
    assert plan.ending_balance == plan.days[-1].balance == Decimal("700")


def test_a_days_balance_closes_after_its_own_events():
    plan = project(
        inputs(liquid_cash="1000", months=[month_of(JULY, funds=[bill("Rent", 20, "300")])])
    )
    assert day_on(plan, date(2026, 7, 19)).balance == Decimal("1000")
    assert day_on(plan, date(2026, 7, 20)).balance == Decimal("700")


# ---------- the wire shape ----------

def test_the_plan_serialises_to_the_shape_the_ui_already_reads():
    # The projection's result is the cash-flow endpoint's response body, so the
    # key order and the string-not-number amounts are a contract, not a detail.
    plan = project(
        inputs(
            liquid_cash="1000",
            paydays=[payday(20, "500")],
            months=[month_of(JULY, funds=[bill("Rent", 20, "300")])],
        )
    )
    body = plan.model_dump(mode="json")

    assert list(body) == [
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
    assert body["month"] == "2026-07-01"
    assert body["today"] == "2026-07-15"
    assert body["min_date"] == "2026-07-01"
    assert body["start_balance"] == "1000"
    assert body["ending_balance"] == "1200"

    day = body["days"][19]
    assert list(day) == ["date", "balance", "events", "is_today"]
    assert day["date"] == "2026-07-20"
    assert day["balance"] == "1200"
    assert day["is_today"] is False
    assert list(day["events"][0]) == ["kind", "label", "amount"]
    assert day["events"] == [
        {"kind": "income", "label": "Paycheck", "amount": "500"},
        {"kind": "outflow", "label": "Rent", "amount": "-300"},
    ]


def test_a_two_place_amount_keeps_its_trailing_zeros_on_the_wire():
    # Amounts come out of Numeric(12, 2) columns, and the UI renders the string
    # as-is — so "1800.00" must not arrive as 1800.0.
    plan = project(
        inputs(liquid_cash="0.00", months=[month_of(JULY, funds=[bill("Rent", 20, "1800.00")])])
    )
    body = plan.model_dump(mode="json")
    assert body["days"][19]["events"][0]["amount"] == "-1800.00"
    assert body["min_balance"] == "-1800.00"
