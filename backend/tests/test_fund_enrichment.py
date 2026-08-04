"""Enrichment of a month's funds: the numbers, and how many statements they cost.

The fixture below covers one fund of every shape the enricher branches on — an
operational fund, a savings goal, a debt goal and a contribution goal — and pins
each derived figure to a literal. Those literals are the characterization: they
were captured from the per-fund implementation before the query fan-out was
collapsed, so a rewrite that changes a balance fails here rather than silently
in production.

The second half pins the statement count. The whole point of the collapse is
that enriching thirty funds costs what enriching four does, and a count that is
merely "better than before" degrades back to a fan-out the moment someone adds
a per-fund lookup.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event

from app import schemas
from app.models import Fund, FundKind, GoalSettlement, GoalType, Transaction, TxType
from app.services.balances import enrich_funds

# A month with history behind it and a month ahead of it, so the fixture proves
# both bounds: what carried in, and what must not be counted yet.
MONTH = date(2026, 3, 1)


@pytest.fixture()
def db(clean_db):
    from app.db import new_session

    with new_session() as session:
        yield session


def _tx(fund: Fund, type_: TxType, amount: str, day: date) -> Transaction:
    return Transaction(fund_id=fund.id, type=type_, amount=Decimal(amount), date=day)


@pytest.fixture()
def funds(db) -> dict[str, Fund]:
    """One fund of each shape, plus a fund deliberately left out of enrichment.

    "Untouched" exists to catch a grouped query that forgets to filter by the
    funds it was handed: its transactions are large enough that leaking them
    into any other fund's total would move that fund's literal.
    """
    groceries = Fund(name="Groceries", kind=FundKind.operational, category="Food", due_day=5)
    emergency = Fund(
        name="Emergency Fund",
        kind=FundKind.goal,
        goal_type=GoalType.savings,
        target=Decimal("10000.00"),
    )
    car_loan = Fund(
        name="Car Loan",
        kind=FundKind.goal,
        goal_type=GoalType.debt,
        target=Decimal("5000.00"),
        min_payment=Decimal("250.00"),
    )
    roth = Fund(
        name="Roth IRA",
        kind=FundKind.goal,
        goal_type=GoalType.contribution,
        target=Decimal("7000.00"),
        target_date=date(2026, 12, 31),
    )
    untouched = Fund(name="Untouched", kind=FundKind.operational)
    db.add_all([groceries, emergency, car_loan, roth, untouched])
    db.flush()

    db.add_all([
        # Operational: rollover from February, then a month mixing an expense,
        # a reimbursement and a transfer — all three net against each other.
        _tx(groceries, TxType.assignment, "400.00", date(2026, 2, 1)),
        _tx(groceries, TxType.expense, "-150.00", date(2026, 2, 20)),
        _tx(groceries, TxType.assignment, "500.00", MONTH),
        _tx(groceries, TxType.expense, "-120.50", date(2026, 3, 12)),
        _tx(groceries, TxType.income, "20.00", date(2026, 3, 14)),
        _tx(groceries, TxType.transfer, "-30.00", date(2026, 3, 28)),
        # April's assignment is beyond the month being viewed and must not show
        # up in any of March's figures.
        _tx(groceries, TxType.assignment, "1000.00", date(2026, 4, 2)),

        _tx(emergency, TxType.assignment, "1000.00", date(2026, 2, 5)),
        _tx(emergency, TxType.assignment, "300.00", date(2026, 3, 5)),

        _tx(car_loan, TxType.assignment, "200.00", date(2026, 2, 10)),
        _tx(car_loan, TxType.assignment, "250.00", date(2026, 3, 10)),
        _tx(car_loan, TxType.expense, "-250.00", date(2026, 3, 11)),

        _tx(roth, TxType.assignment, "583.33", date(2026, 3, 15)),

        _tx(untouched, TxType.assignment, "9999.00", MONTH),
        _tx(untouched, TxType.expense, "-4321.00", date(2026, 3, 20)),
    ])

    db.add_all([
        GoalSettlement(goal_id=emergency.id, amount=Decimal("250.00"), settled_at=date(2026, 3, 6)),
        # Contribution goals count the tax year, not the month: January counts,
        # last December does not.
        GoalSettlement(goal_id=roth.id, amount=Decimal("500.00"), settled_at=date(2026, 1, 20)),
        GoalSettlement(goal_id=roth.id, amount=Decimal("583.33"), settled_at=date(2026, 3, 16)),
        GoalSettlement(goal_id=roth.id, amount=Decimal("400.00"), settled_at=date(2025, 12, 15)),
    ])
    db.flush()

    return {
        "groceries": groceries,
        "emergency": emergency,
        "car_loan": car_loan,
        "roth": roth,
        "untouched": untouched,
    }


#: What every fund in the fixture is worth in March 2026. Captured from the
#: per-fund implementation; the collapsed queries must reproduce it exactly.
EXPECTED = {
    "groceries": {
        "balance": "619.50",              # 250 rollover + 500 - 120.50 + 20 - 30
        "net_spent_this_month": "130.50",  # 120.50 + 30 transfer - 20 reimbursed
        "assigned_this_month": "500.00",
        "available_this_month": "750.00",  # 250 rollover + 500 assigned
        "contribution_ytd": None,
        "contribution_year": None,
    },
    "emergency": {
        "balance": "1300.00",
        "net_spent_this_month": "0",
        "assigned_this_month": "300.00",
        "available_this_month": "1300.00",
        "contribution_ytd": None,
        "contribution_year": None,
    },
    "car_loan": {
        "balance": "200.00",
        "net_spent_this_month": "250.00",
        "assigned_this_month": "250.00",
        "available_this_month": "450.00",
        "contribution_ytd": None,
        "contribution_year": None,
    },
    "roth": {
        "balance": "583.33",
        "net_spent_this_month": "0",
        "assigned_this_month": "583.33",
        "available_this_month": "583.33",
        "contribution_ytd": "1083.33",     # January + March; last December is a different year
        "contribution_year": 2026,
    },
}

MONEY_FIELDS = (
    "balance",
    "net_spent_this_month",
    "assigned_this_month",
    "available_this_month",
)


def _actual(enriched) -> dict[str, object]:
    """The derived half of an enrichment, as plain comparable values."""
    return {
        **{f: getattr(enriched, f) for f in MONEY_FIELDS},
        "contribution_ytd": enriched.contribution_ytd,
        "contribution_year": enriched.contribution_year,
    }


def _expected(key: str) -> dict[str, object]:
    want = EXPECTED[key]
    ytd = want["contribution_ytd"]
    return {
        **{f: Decimal(str(want[f])) for f in MONEY_FIELDS},
        "contribution_ytd": None if ytd is None else Decimal(str(ytd)),
        "contribution_year": want["contribution_year"],
    }


#: The four shapes, enriched as one set — which is the whole interface now.
SHAPES = list(EXPECTED)


@pytest.fixture()
def enriched(db, funds) -> dict[str, object]:
    result = enrich_funds(db, [funds[k] for k in SHAPES], MONTH)
    return dict(zip(SHAPES, result))


@pytest.mark.parametrize("key", SHAPES)
def test_enrichment_matches_the_per_fund_figures(enriched, key):
    assert _actual(enriched[key]) == _expected(key)


def test_enrichment_returns_the_declared_response_schema(enriched, funds):
    """The schema itself, not a dict shaped like it.

    The declared fields have to survive the trip too: they are what makes
    building `FundOut` from the fund cheaper than restating it field by field.
    """
    groceries = enriched["groceries"]
    assert isinstance(groceries, schemas.FundOut)
    assert (groceries.id, groceries.name) == (funds["groceries"].id, "Groceries")
    assert (groceries.kind, groceries.category, groceries.due_day) == (
        FundKind.operational,
        "Food",
        5,
    )

    car_loan = enriched["car_loan"]
    assert (car_loan.kind, car_loan.goal_type) == (FundKind.goal, GoalType.debt)
    assert (car_loan.target, car_loan.min_payment) == (
        Decimal("5000.00"),
        Decimal("250.00"),
    )


def test_a_fund_with_no_transactions_enriches_to_zero(db):
    """No row comes back from a grouped scan for a fund that has nothing in it,
    which is a different code path from summing an empty set per fund."""
    fresh = Fund(name="Brand New", kind=FundKind.operational)
    db.add(fresh)
    db.flush()

    (out,) = enrich_funds(db, [fresh], MONTH)
    assert _actual(out) == {
        "balance": Decimal("0"),
        "net_spent_this_month": Decimal("0"),
        "assigned_this_month": Decimal("0"),
        "available_this_month": Decimal("0"),
        "contribution_ytd": None,
        "contribution_year": None,
    }


def test_a_contribution_goal_without_a_target_date_uses_the_viewed_year(db):
    """The other half of the tax-year rule the March fixture doesn't reach."""
    hsa = Fund(name="HSA", kind=FundKind.goal, goal_type=GoalType.contribution)
    db.add(hsa)
    db.flush()
    db.add_all([
        GoalSettlement(goal_id=hsa.id, amount=Decimal("100.00"), settled_at=date(2026, 2, 1)),
        GoalSettlement(goal_id=hsa.id, amount=Decimal("75.00"), settled_at=date(2025, 11, 1)),
    ])
    db.flush()

    (out,) = enrich_funds(db, [hsa], MONTH)
    assert out.contribution_year == MONTH.year
    assert out.contribution_ytd == Decimal("100.00")


@contextmanager
def _counting(engine) -> Generator[list[str]]:
    """Every statement sent over `engine` while inside the block."""
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _lots_of_funds(db, count: int) -> list[Fund]:
    """`count` funds spanning the shapes that make the enricher branch.

    Contribution goals are in the mix deliberately: they are what triggers the
    second query, so their presence must not scale with anything either.
    """
    made = []
    for i in range(count):
        goal = i % 3 == 0
        made.append(
            Fund(
                name=f"Fund {i}",
                kind=FundKind.goal if goal else FundKind.operational,
                goal_type=GoalType.contribution if goal else None,
            )
        )
    db.add_all(made)
    db.flush()
    db.add_all([
        _tx(f, TxType.assignment, "100.00", date(2026, 3, 4)) for f in made
    ])
    db.add_all([
        GoalSettlement(goal_id=f.id, amount=Decimal("25.00"), settled_at=date(2026, 2, 2))
        for f in made
        if f.goal_type is GoalType.contribution
    ])
    db.flush()
    return made


#: Two grouped queries: one over transactions, one over goal settlements. The
#: literal is the point of the test — "fewer than before" would drift back.
EXPECTED_STATEMENTS = 2


def test_the_statement_count_does_not_grow_with_the_funds(db, funds, engine):
    four = [funds[k] for k in SHAPES]
    with _counting(engine) as for_four:
        enrich_funds(db, four, MONTH)

    forty = _lots_of_funds(db, 40)
    with _counting(engine) as for_forty:
        enrich_funds(db, forty, MONTH)

    assert len(for_four) == EXPECTED_STATEMENTS, for_four
    assert len(for_forty) == EXPECTED_STATEMENTS, for_forty


def test_enriching_nothing_asks_the_database_nothing(db, engine):
    with _counting(engine) as statements:
        assert enrich_funds(db, [], MONTH) == []
    assert statements == []
