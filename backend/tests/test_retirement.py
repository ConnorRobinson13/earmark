"""The retirement recurrence, exercised without a database.

These are the numbers the web app and the MCP tool both used to work out for
themselves, and they disagreed: one escalated the yearly contribution and could
deflate the result into today's dollars, the other did neither. So the cases
that separate the two versions — escalation and deflation — are pinned here,
along with the degenerate ones that used to be nobody's job to think about.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.retirement import ProjectionParams, project


def params(**overrides) -> ProjectionParams:
    """A projection with every dial off: no return, no contribution, no growth,
    no inflation. Each test turns on only the one it is about."""
    return ProjectionParams(
        **{
            "current_age": 30,
            "retire_age": 40,
            "annual_return_pct": Decimal("0"),
            "monthly_contribution": Decimal("0"),
            "contribution_growth_pct": Decimal("0"),
            "inflation_pct": Decimal("0"),
            **overrides,
        }
    )


def test_zero_years_returns_the_balance_you_started_with():
    p = project(params(current_age=65, retire_age=65), Decimal("10000"))

    assert p.years == 0
    assert p.final_nominal == Decimal("10000.00")
    assert p.total_contributed == Decimal("0.00")
    assert p.compounded_growth == Decimal("0.00")
    # One point, so a chart drawn from this has something to draw.
    assert [pt.year for pt in p.series] == [0]


def test_retiring_before_today_is_zero_years_rather_than_negative():
    # The web app clamped this with `Math.max(0, ...)` and the MCP tool with
    # `max(0, ...)`; the clamp belongs with the recurrence, not with each caller.
    p = project(params(current_age=65, retire_age=40), Decimal("10000"))

    assert p.years == 0
    assert p.final_nominal == Decimal("10000.00")


def test_zero_contributions_compounds_the_starting_balance_alone():
    p = project(
        params(current_age=30, retire_age=32, annual_return_pct=Decimal("10")),
        Decimal("10000"),
    )

    assert [pt.nominal for pt in p.series] == [
        Decimal("10000.00"),
        Decimal("11000.00"),
        Decimal("12100.00"),
    ]
    assert p.total_contributed == Decimal("0.00")
    assert p.compounded_growth == Decimal("2100.00")


def test_contributions_land_a_year_at_a_time():
    p = project(
        params(current_age=30, retire_age=32, monthly_contribution=Decimal("100")),
        Decimal("0"),
    )

    assert [pt.contributed for pt in p.series] == [
        Decimal("0.00"),
        Decimal("1200.00"),
        Decimal("2400.00"),
    ]
    assert p.final_nominal == Decimal("2400.00")


def test_contributions_escalate_by_the_growth_rate():
    # Year 1 pays the base amount, and every year after it grows — the raises
    # the web app modelled and the MCP tool did not.
    p = project(
        params(
            current_age=30,
            retire_age=32,
            monthly_contribution=Decimal("100"),
            contribution_growth_pct=Decimal("10"),
        ),
        Decimal("0"),
    )

    assert [pt.contributed for pt in p.series] == [
        Decimal("0.00"),
        Decimal("1200.00"),
        Decimal("2520.00"),  # 1200 + 1200 × 1.10
    ]
    assert p.total_contributed == Decimal("2520.00")


def test_inflation_deflates_the_series_into_todays_dollars():
    p = project(
        params(current_age=30, retire_age=32, inflation_pct=Decimal("10")),
        Decimal("1000"),
    )

    # Nothing compounds, so the nominal line is flat while the real one falls.
    assert [pt.nominal for pt in p.series] == [Decimal("1000.00")] * 3
    assert [pt.real for pt in p.series] == [
        Decimal("1000.00"),
        Decimal("909.09"),   # 1000 / 1.1
        Decimal("826.45"),   # 1000 / 1.21
    ]
    assert p.final_real == Decimal("826.45")


def test_without_inflation_todays_dollars_are_the_nominal_ones():
    p = project(
        params(current_age=30, retire_age=40, annual_return_pct=Decimal("7")),
        Decimal("25000"),
    )

    assert [pt.real for pt in p.series] == [pt.nominal for pt in p.series]
    assert p.final_real == p.final_nominal


def test_growth_is_whatever_the_balance_did_not_come_from():
    # The one decomposition, written once: both clients used to spell out
    # `final − start − contributed` themselves.
    p = project(
        params(
            current_age=28,
            retire_age=65,
            annual_return_pct=Decimal("8"),
            monthly_contribution=Decimal("583"),
            contribution_growth_pct=Decimal("3"),
            inflation_pct=Decimal("2.5"),
        ),
        Decimal("42000"),
    )

    assert (
        p.starting_balance + p.total_contributed + p.compounded_growth
        == p.final_nominal
    )
    assert p.final_nominal > p.final_real > 0


def test_the_series_is_labelled_by_age_as_well_as_by_year():
    p = project(params(current_age=28, retire_age=31), Decimal("0"))

    assert [(pt.year, pt.age) for pt in p.series] == [
        (0, 28), (1, 29), (2, 30), (3, 31),
    ]


def test_the_final_point_is_the_headline():
    p = project(
        params(
            current_age=30,
            retire_age=35,
            annual_return_pct=Decimal("6"),
            monthly_contribution=Decimal("250"),
            inflation_pct=Decimal("2"),
        ),
        Decimal("5000"),
    )

    assert p.final_nominal == p.series[-1].nominal
    assert p.final_real == p.series[-1].real
    assert p.total_contributed == p.series[-1].contributed


@pytest.mark.parametrize(
    "bad",
    [
        {"inflation_pct": Decimal("-100")},   # a zero deflator: divides by nothing
        {"monthly_contribution": Decimal("-1")},
        {"current_age": -1},
        {"retire_age": 200},
    ],
)
def test_impossible_dials_are_refused(bad):
    with pytest.raises(ValueError):
        params(**bad)
