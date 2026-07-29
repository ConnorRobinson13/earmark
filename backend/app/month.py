"""Everything the app knows about a calendar month.

A month is a `date` pinned to its first day. That is already the repo's storage
convention (`monthly_meta.month`, `net_worth_snapshots.month`, a fund's
`effective_to_month`), so normalising at the edge means the same value flows from
the query string through the services into the database without anyone having to
remember which functions tolerate a mid-month date.

Two wire forms are accepted, `YYYY-MM` and `YYYY-MM-DD`, and both land on the
first of the month. Nothing else parses — in particular the compact `YYYYMMDD`
and ISO week forms that `date.fromisoformat` happens to allow are rejected, so
"a month" means one of two shapes rather than "whatever the stdlib swallows".

Pure by design: no database, no settings, no FastAPI. It is importable and
testable on its own, which is why the routers can share it without any of them
growing a dependency on the others.
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, timedelta

#: The one message every endpoint gives back for a month it cannot read.
INVALID_MONTH_DETAIL = "month must be YYYY-MM or YYYY-MM-DD"

_SHORT = re.compile(r"^(\d{4})-(\d{2})$")
_LONG = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class InvalidMonth(ValueError):
    """A string that is neither `YYYY-MM` nor `YYYY-MM-DD`.

    `app.main` maps this to a 400 so no router needs its own try/except, and
    every endpoint answers an unreadable month identically. The offending value
    is deliberately left out of the message, so the response is the same string
    no matter what was sent.
    """

    def __init__(self) -> None:
        super().__init__(INVALID_MONTH_DETAIL)


def parse_month(raw: str) -> date:
    """Read `YYYY-MM` or `YYYY-MM-DD` as the first of that month.

    Raises `InvalidMonth` for anything else, including a well-formed string
    naming a day that doesn't exist (`2026-02-30`).
    """
    if short := _SHORT.match(raw):
        year, month = int(short[1]), int(short[2])
        day = 1
    elif long := _LONG.match(raw):
        year, month, day = int(long[1]), int(long[2]), int(long[3])
    else:
        raise InvalidMonth

    try:
        parsed = date(year, month, day)
    except ValueError as exc:  # month 13, February 30th, …
        raise InvalidMonth from exc
    return parsed.replace(day=1)


def first_of_month(d: date) -> date:
    """The first of the month containing `d`."""
    return d.replace(day=1)


def next_month(d: date) -> date:
    """The first of the month after the one containing `d`."""
    first = first_of_month(d)
    if first.month == 12:
        return first.replace(year=first.year + 1, month=1)
    return first.replace(month=first.month + 1)


def month_bounds(d: date) -> tuple[date, date]:
    """`(first_of_month, first_of_next_month)` — the upper bound is exclusive."""
    return first_of_month(d), next_month(d)


def days_in_month(d: date) -> int:
    """Number of days in the month containing `d`."""
    return monthrange(d.year, d.month)[1]


def last_day_of_month(d: date) -> date:
    """The last day of the month containing `d` — the inclusive upper bound."""
    return d.replace(day=days_in_month(d))


def previous_month(d: date) -> date:
    """The first of the month before the one containing `d`."""
    return first_of_month(first_of_month(d) - timedelta(days=1))


def clamp_day_to_month(day: int, d: date) -> date:
    """The date in `d`'s month for day-of-month `day`, clamped to the month
    length — day 31 in February gives the 28th (or 29th in a leap year)."""
    first = first_of_month(d)
    return first.replace(day=min(day, days_in_month(first)))


def current_month(today: date | None = None) -> date:
    """The first of the month we are in now."""
    return first_of_month(today or date.today())


def is_current_month(d: date, today: date | None = None) -> bool:
    """Whether `d` falls in the month we are in now."""
    return first_of_month(d) == current_month(today)


def parse_month_or_current(raw: str | None, today: date | None = None) -> date:
    """`parse_month(raw)`, or the current month when `raw` is absent or empty.

    The shape every month query parameter wants: optional, defaulting to now,
    and rejecting a value that was supplied but unreadable.
    """
    if not raw:
        return current_month(today)
    return parse_month(raw)
