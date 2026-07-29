"""The month value module: parsing, bounds, and current-ness.

Pure — no database, no app import beyond `app.month` itself. Expected values are
written out as literals from a calendar, not recomputed the way the module does.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.month import (
    InvalidMonth,
    clamp_day_to_month,
    current_month,
    days_in_month,
    first_of_month,
    is_current_month,
    last_day_of_month,
    month_bounds,
    next_month,
    parse_month,
    parse_month_or_current,
    previous_month,
)


def test_parses_the_short_form_to_the_first_of_that_month():
    assert parse_month("2026-07") == date(2026, 7, 1)


def test_parses_the_long_form_and_normalises_to_the_first():
    assert parse_month("2026-07-15") == date(2026, 7, 1)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "2026",
        "2026-",
        "2026-7",
        "2026-13",
        "2026-00",
        "2026-07-",
        "2026-7-1",
        "2026-02-30",
        "2026-06-31",
        "20260715",
        "2026-W01-1",
        "2026-07-15T00:00",
        "July 2026",
    ],
)
def test_rejects_anything_that_is_not_one_of_the_two_forms(raw):
    with pytest.raises(InvalidMonth):
        parse_month(raw)


def test_first_of_month_pins_a_mid_month_date_to_the_first():
    assert first_of_month(date(2026, 7, 15)) == date(2026, 7, 1)


def test_bounds_are_the_first_and_the_first_of_the_next_month():
    assert month_bounds(date(2026, 7, 15)) == (date(2026, 7, 1), date(2026, 8, 1))


def test_bounds_roll_the_year_over_from_december_to_january():
    assert month_bounds(date(2026, 12, 9)) == (date(2026, 12, 1), date(2027, 1, 1))


def test_next_month_rolls_the_year_over_from_december_to_january():
    assert next_month(date(2026, 12, 31)) == date(2027, 1, 1)


def test_last_day_of_a_31_day_month():
    assert last_day_of_month(date(2026, 7, 15)) == date(2026, 7, 31)


def test_last_day_of_december_stays_in_december():
    assert last_day_of_month(date(2026, 12, 1)) == date(2026, 12, 31)


def test_last_day_of_february_in_a_common_year():
    assert last_day_of_month(date(2026, 2, 1)) == date(2026, 2, 28)


def test_last_day_of_february_in_a_leap_year():
    assert last_day_of_month(date(2028, 2, 1)) == date(2028, 2, 29)


def test_previous_month_rolls_the_year_back_from_january_to_december():
    assert previous_month(date(2027, 1, 15)) == date(2026, 12, 1)


def test_days_in_month_for_february_in_a_leap_year():
    assert days_in_month(date(2028, 2, 1)) == 29


def test_clamping_day_31_into_february_lands_on_the_28th():
    assert clamp_day_to_month(31, date(2026, 2, 1)) == date(2026, 2, 28)


def test_clamping_a_day_the_month_has_leaves_it_alone():
    assert clamp_day_to_month(15, date(2026, 7, 1)) == date(2026, 7, 15)


def test_the_month_holding_today_is_the_current_one():
    assert is_current_month(date(2026, 7, 31), today=date(2026, 7, 1)) is True


def test_last_december_is_not_the_current_month_in_january():
    assert is_current_month(date(2026, 12, 31), today=date(2027, 1, 1)) is False


def test_current_month_is_todays_month_pinned_to_the_first():
    assert current_month(today=date(2026, 7, 15)) == date(2026, 7, 1)


def test_an_absent_month_falls_back_to_the_current_one():
    assert parse_month_or_current(None, today=date(2026, 7, 15)) == date(2026, 7, 1)


def test_an_empty_month_falls_back_to_the_current_one():
    assert parse_month_or_current("", today=date(2026, 7, 15)) == date(2026, 7, 1)


def test_a_supplied_month_wins_over_today():
    assert parse_month_or_current("2026-03", today=date(2026, 7, 15)) == date(2026, 3, 1)


def test_an_unparseable_month_is_still_rejected_when_a_fallback_exists():
    with pytest.raises(InvalidMonth):
        parse_month_or_current("nope", today=date(2026, 7, 15))
