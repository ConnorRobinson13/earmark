"""The cash-flow projection: a month of liquid cash, day by day.

The plan it draws is deliberately simple. Each fund's *full assigned amount*
leaves the account on its `due_day`, each payday lands its income on its day,
and the running balance is anchored to reality by working back from the cash in
the account right now — so the balance shown for *today* is the real one, and
the days either side of it are reconstructed or projected from that point.

Pure by design: no database, no settings, no FastAPI. Everything the projection
needs arrives as a `CashflowInputs`, and `app.services.balances.gather_cashflow_inputs`
is the single place that reads those values out of Postgres. That split is the
point — the payday even-split, the anchor back-solve and the day walk are the
most intricate arithmetic in the backend, and none of it should need a database
to exercise.

`CashflowPlan` is also the cash-flow endpoint's response body. Its amounts are
`Decimal`, which pydantic renders as JSON strings, because a projected balance
rounded through a float is a wrong number on someone's screen.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from .month import clamp_day_to_month, first_of_month, last_day_of_month


# ---------- Inputs ----------

class Payday(BaseModel):
    """One recurring payday.

    `amount` set means a fixed deposit. `amount` absent means this payday takes
    an even share of whatever planned income the fixed ones leave behind.
    """

    day_of_month: int  # 1-31, clamped to the month's length when it lands
    amount: Decimal | None = None


class FundCharge(BaseModel):
    """A fund's whole monthly assignment, leaving the account on `due_day`."""

    name: str
    due_day: int  # 1-31, clamped the same way a payday is
    assigned: Decimal  # positive: what the fund was assigned this month


class MonthInputs(BaseModel):
    """What one month of the span contributes: the income it plans for, and the
    funds drawing on it."""

    month: date  # pinned to the first of the month
    planned_income: Decimal
    funds: list[FundCharge] = []


class CashflowInputs(BaseModel):
    """Everything the projection needs, already read out of the database.

    `months` runs from the current month through the selected one, in order.
    The span reaches back that far because the running balance is anchored to
    today's real cash: projecting a later month means walking the months in
    between so the anchor can carry forward. It is empty for a month that is
    already over, which short-circuits before any of it is read.
    """

    today: date
    month: date  # the selected month, pinned to its first day
    liquid_cash: Decimal  # spendable cash in the account right now
    paydays: list[Payday] = []
    months: list[MonthInputs] = []


# ---------- The plan ----------

class CashflowEvent(BaseModel):
    """Money moving on a day. Signed: income adds, an outflow subtracts."""

    kind: Literal["income", "outflow"]
    label: str
    amount: Decimal


class CashflowDay(BaseModel):
    """One day of the selected month. `balance` closes the day — it is the
    balance *after* that day's events, which is what the UI stacks per card."""

    date: date
    balance: Decimal
    events: list[CashflowEvent]
    is_today: bool


class CashflowPlan(BaseModel):
    """The projection for one month, one entry per day.

    Field order is the endpoint's response body, so it is a contract with the
    UI rather than a matter of taste.
    """

    month: date  # the selected month, pinned to its first day
    past: bool
    today: date
    start_balance: Decimal  # carried into the first day, before its events
    ending_balance: Decimal
    min_balance: Decimal
    min_date: date
    goes_negative: bool
    days: list[CashflowDay]


def project(inputs: CashflowInputs) -> CashflowPlan:
    """Draw the day-by-day plan for `inputs.month`."""
    sel_first = first_of_month(inputs.month)
    sel_end = last_day_of_month(sel_first)

    # A month already over cannot be reconstructed day by day: we know what the
    # account holds now, not what it held on each of those days. Report today's
    # cash flatly rather than drawing a line that would be fiction.
    if sel_end < inputs.today:
        return CashflowPlan(
            month=sel_first,
            past=True,
            today=inputs.today,
            start_balance=inputs.liquid_cash,
            ending_balance=inputs.liquid_cash,
            min_balance=inputs.liquid_cash,
            min_date=inputs.today,
            goes_negative=False,
            days=[],
        )

    events = _events(inputs)

    # Anchor: pick the balance carried into the start of the span so that the
    # running balance on `today` lands exactly on current liquid cash.
    #   balance(today) = span_start + Σ(events dated ≤ today)  ==  liquid_cash
    consumed = sum((e.amount for when, e in events if when <= inputs.today), Decimal("0"))
    span_start = inputs.liquid_cash - consumed

    # Walk the whole span day by day — the months before the selected one only
    # carry the running balance forward — and keep the selected month's days.
    span_first = inputs.months[0].month if inputs.months else sel_first
    days: list[CashflowDay] = []
    running = span_start
    carried_in = span_start  # balance carried into the first selected day
    min_balance: Decimal | None = None
    min_date = sel_first
    ei = 0
    d = span_first
    while d <= sel_end:
        if d == sel_first:
            carried_in = running
        day_events: list[CashflowEvent] = []
        while ei < len(events) and events[ei][0] == d:
            running += events[ei][1].amount
            day_events.append(events[ei][1])
            ei += 1
        if d >= sel_first:
            days.append(
                CashflowDay(
                    date=d,
                    balance=running,
                    events=day_events,
                    is_today=d == inputs.today,
                )
            )
            # Strictly lower, so a balance touched twice reports the first day
            # it was reached — that is the one worth warning about.
            if min_balance is None or running < min_balance:
                min_balance = running
                min_date = d
        d += timedelta(days=1)

    # No days at all only happens for a span that ends before it starts, which
    # the past-month branch above has already ruled out.
    low = min_balance if min_balance is not None else span_start

    return CashflowPlan(
        month=sel_first,
        past=False,
        today=inputs.today,
        start_balance=carried_in,
        ending_balance=running,
        min_balance=low,
        min_date=min_date,
        goes_negative=low < 0,
        days=days,
    )


def _events(inputs: CashflowInputs) -> list[tuple[date, CashflowEvent]]:
    """Every dated event across the span, in day order.

    The sort is stable, so events sharing a day keep the order they were built
    in — a month's paychecks before its bills — which is the order the day's
    card lists them.
    """
    events: list[tuple[date, CashflowEvent]] = []
    for m in inputs.months:
        for pay, amount in _payday_deposits(inputs.paydays, m.planned_income):
            if amount == 0:
                continue  # a payday with nothing to deposit is not an event
            events.append(
                (
                    clamp_day_to_month(pay.day_of_month, m.month),
                    CashflowEvent(kind="income", label="Paycheck", amount=amount),
                )
            )
        for fund in m.funds:
            if fund.assigned == 0:
                continue
            events.append(
                (
                    clamp_day_to_month(fund.due_day, m.month),
                    CashflowEvent(kind="outflow", label=fund.name, amount=-fund.assigned),
                )
            )
    events.sort(key=lambda dated: dated[0])
    return events


def _payday_deposits(
    paydays: list[Payday], planned_income: Decimal
) -> list[tuple[Payday, Decimal]]:
    """Pair every payday with the deposit it lands.

    Fixed-amount paydays come off the top; whatever planned income is left is
    split evenly across the paydays that name no amount. With none of those,
    the remainder simply goes unpaid — it has no payday to land on.
    """
    fixed_total = sum((p.amount for p in paydays if p.amount is not None), Decimal("0"))
    split_count = sum(1 for p in paydays if p.amount is None)
    split_each = (planned_income - fixed_total) / split_count if split_count else Decimal("0")
    return [(p, p.amount if p.amount is not None else split_each) for p in paydays]
