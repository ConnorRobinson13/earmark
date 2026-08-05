"""The retirement projection: one compounding recurrence for every caller.

This recurrence used to live in two places and agreed in neither. The web app
escalated the yearly contribution by a growth rate and could deflate the result
into today's dollars; the MCP tool did neither, so asking Claude and asking the
net-worth page the same question returned two different numbers. Both also
spelled out the growth decomposition — final less start less contributions — for
themselves. All of it lives here now, and both clients read it over HTTP.

Pure by design, in the same spirit as `app.services.cashflow`: no database, no
settings, no FastAPI. The one figure that has to be looked up — the investment
balance the projection starts from — arrives as an argument, so the arithmetic
can be exercised without Postgres behind it.

Amounts are `Decimal` for the reason they are everywhere else in this backend:
a balance rounded through a float is a wrong number on someone's screen. They
are quantized to cents only on the way out, so the recurrence itself compounds
at full precision.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, Field, computed_field

CENTS = Decimal("0.01")


def _cents(amount: Decimal) -> Decimal:
    """Round to the nearest cent, halves up — how money is written down."""
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class ProjectionParams(BaseModel):
    """The dials a caller turns.

    Every one of them is an assumption about the future, so none of them is
    derived here — the endpoint takes them as query parameters and hands them
    over as given. The bounds only rule out arithmetic that has no meaning: an
    inflation rate of exactly −100% would deflate by zero.
    """

    current_age: int = Field(ge=0, le=120)
    retire_age: int = Field(ge=0, le=120)

    #: Nominal annual return on the whole balance, compounded once a year.
    annual_return_pct: Decimal = Field(default=Decimal("8"), ge=-100, le=100)

    #: What goes in each month of the *first* year; later years escalate.
    monthly_contribution: Decimal = Field(default=Decimal("0"), ge=0)

    #: How much the yearly contribution grows each year — raises. 0 = flat.
    contribution_growth_pct: Decimal = Field(default=Decimal("0"), ge=-100, le=100)

    #: Deflates the series into today's dollars. 0 = real equals nominal.
    inflation_pct: Decimal = Field(default=Decimal("0"), gt=-100, le=100)

    @computed_field
    @property
    def years(self) -> int:
        """Whole years left to compound, floored at zero.

        Both clients clamped this themselves, because a retirement age already
        behind you would otherwise run the loop backwards. The clamp belongs
        with the recurrence rather than with each caller — and computed rather
        than stored so it cannot be passed in disagreeing with the two ages.
        """
        return max(0, self.retire_age - self.current_age)


class ProjectionPoint(BaseModel):
    """One year on the chart.

    Carries the balance both ways round. Whether to show future dollars or
    today's is a display choice, and answering it in the response means the
    toggle on the page costs no round trip.
    """

    year: int
    age: int
    nominal: Decimal  # future dollars, as the account would read
    real: Decimal  # the same money in today's dollars
    contributed: Decimal  # cumulative contributions up to and including this year


class RetirementProjection(ProjectionParams):
    """The projection, and the assumptions it was drawn under.

    The parameters are echoed back deliberately: this is the endpoint's response
    body, and a client charting it should not have to remember what it asked for
    to label the chart. Inherited rather than restated so a new dial is one
    edit — the two lists cannot fall out of step if there is only one list.
    """

    starting_balance: Decimal
    total_contributed: Decimal
    compounded_growth: Decimal
    final_nominal: Decimal
    final_real: Decimal
    series: list[ProjectionPoint]


def project(params: ProjectionParams, starting_balance: Decimal) -> RetirementProjection:
    """Compound `starting_balance` to retirement, one year at a time.

    The model is deliberately coarse: the whole balance earns the annual return
    once a year and the year's contributions land at the end of it. Nothing here
    is precise enough to justify monthly compounding — the return itself is a
    guess — and a year is the granularity the chart draws anyway.
    """
    annual_return = params.annual_return_pct / 100
    contribution_growth = params.contribution_growth_pct / 100
    inflation = params.inflation_pct / 100

    balance = starting_balance
    annual_contribution = params.monthly_contribution * 12
    contributed = Decimal("0")
    # Carried forward rather than raised to a power each year: the walk already
    # visits every year, and repeated multiplication keeps the two lines exactly
    # in step at every point.
    deflator = Decimal("1")

    series = [
        ProjectionPoint(
            year=0,
            age=params.current_age,
            nominal=_cents(balance),
            real=_cents(balance),
            contributed=Decimal("0.00"),
        )
    ]
    for year in range(1, params.years + 1):
        balance = balance * (1 + annual_return) + annual_contribution
        contributed += annual_contribution
        deflator *= 1 + inflation
        series.append(
            ProjectionPoint(
                year=year,
                age=params.current_age + year,
                nominal=_cents(balance),
                real=_cents(balance / deflator),
                contributed=_cents(contributed),
            )
        )
        # Next year's contribution grows with raises.
        annual_contribution *= 1 + contribution_growth

    started_with = _cents(starting_balance)
    put_in = _cents(contributed)
    return RetirementProjection(
        # `years` is computed from the two ages, so it is not passed along here.
        **params.model_dump(exclude={"years"}),
        starting_balance=started_with,
        total_contributed=put_in,
        # Whatever the balance did not come from: not the money put in, and not
        # the money already there. Written once so no client has to derive it,
        # and derived from the rounded figures rather than the exact ones so the
        # three numbers on screen still add up to the total above them.
        compounded_growth=series[-1].nominal - started_with - put_in,
        final_nominal=series[-1].nominal,
        final_real=series[-1].real,
        series=series,
    )
