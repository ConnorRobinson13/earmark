"""The net-worth service: the breakdown, the formula, and the snapshot.

These talk to the service directly rather than over HTTP, because the things
worth pinning down here are arithmetic — which account types count as what, and
that a debt fund paid past its target stops helping. The HTTP contract is
covered separately in `test_networth_api.py`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import db as db_module
from app.models import Account, AccountType, Fund, FundKind, GoalType, Transaction, TxType
from app.services import networth as svc
from app.services.balances import liquid_cash


@pytest.fixture()
def db(clean_db):
    """A session the test owns, against the same throwaway database."""
    s = db_module.new_session()
    try:
        yield s
    finally:
        s.close()


def _account(db, name: str, type_: AccountType, balance: str) -> Account:
    a = Account(name=name, type=type_, current_balance=Decimal(balance))
    db.add(a)
    db.flush()
    return a


def _debt_fund(db, name: str, target: str, paid: str = "0") -> Fund:
    f = Fund(
        name=name,
        kind=FundKind.goal,
        goal_type=GoalType.debt,
        target=Decimal(target),
    )
    db.add(f)
    db.flush()
    if Decimal(paid):
        db.add(
            Transaction(
                fund_id=f.id,
                type=TxType.assignment,
                amount=Decimal(paid),
                date=date.today(),
            )
        )
        db.flush()
    return f


def test_remaining_debt_is_what_is_still_owed(db):
    fund = _debt_fund(db, "Car loan", target="10000.00", paid="2500.00")
    assert svc.remaining_debt(db, fund) == Decimal("7500.00")


def test_remaining_debt_stops_at_zero_when_overpaid(db):
    """An overpaid debt fund is settled, not an asset — it must not add to net
    worth by going negative."""
    fund = _debt_fund(db, "Student loan", target="1000.00", paid="1400.00")
    assert svc.remaining_debt(db, fund) == Decimal("0")


def test_total_remaining_debt_skips_archived_and_non_debt_funds(db):
    _debt_fund(db, "Car loan", target="10000.00", paid="2500.00")
    _debt_fund(db, "Card payoff", target="500.00")

    archived = _debt_fund(db, "Old loan", target="9999.00")
    archived.archived_at = date.today()

    savings_goal = Fund(
        name="Vacation",
        kind=FundKind.goal,
        goal_type=GoalType.savings,
        target=Decimal("3000.00"),
    )
    operational = Fund(name="Groceries", kind=FundKind.operational)
    db.add_all([savings_goal, operational])
    db.flush()

    assert svc.total_remaining_debt(db) == Decimal("8000.00")


def test_net_worth_adds_assets_and_subtracts_debts(db):
    _account(db, "Checking", AccountType.checking, "1500.00")
    _account(db, "Savings", AccountType.savings, "2000.00")
    _account(db, "Brokerage", AccountType.investment, "12000.00")
    _account(db, "Rainy day", AccountType.emergency_fund, "5000.00")
    _account(db, "Visa", AccountType.credit, "800.00")
    _debt_fund(db, "Car loan", target="10000.00", paid="2500.00")

    nw = svc.compute_net_worth(db)

    assert nw.liquid == Decimal("3500.00")
    assert nw.investment == Decimal("12000.00")
    assert nw.emergency_fund == Decimal("5000.00")
    assert nw.credit_debt == Decimal("800.00")
    assert nw.loan_debt == Decimal("7500.00")
    # 3500 + 12000 + 5000 − 800 − 7500
    assert nw.total == Decimal("12200.00")


def test_liquid_is_the_same_number_the_dashboard_uses(db):
    """One definition of spendable cash. Emergency-fund and investment balances
    are excluded from it by `balances.liquid_cash`, and net worth must not
    quietly draw its own line somewhere else."""
    _account(db, "Checking", AccountType.checking, "1500.00")
    _account(db, "Savings", AccountType.savings, "2000.00")
    _account(db, "Rainy day", AccountType.emergency_fund, "5000.00")
    _account(db, "Brokerage", AccountType.investment, "12000.00")

    assert svc.compute_net_worth(db).liquid == liquid_cash(db)


def test_by_type_carries_every_account_type_even_at_zero(db):
    _account(db, "Checking", AccountType.checking, "100.00")

    by_type = svc.compute_net_worth(db).by_type

    assert set(by_type) == {t.value for t in AccountType}
    assert by_type["checking"] == Decimal("100.00")
    assert by_type["credit"] == Decimal("0")


def test_capture_snapshot_is_idempotent_within_a_month(db):
    _account(db, "Checking", AccountType.checking, "1000.00")

    first = svc.capture_snapshot(db)
    db.commit()
    assert first.total == Decimal("1000.00")

    db.query(Account).update({Account.current_balance: Decimal("1750.00")})
    second = svc.capture_snapshot(db)
    db.commit()

    assert svc.snapshot_history(db) == [second]
    assert second.month == first.month
    assert second.total == Decimal("1750.00")
