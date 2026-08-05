"""Which funds are active in a month — the one definition, and its callers.

`active_funds_in_month` is the predicate; the dashboard, the bulk copy and the
cash-flow projector all read the month's funds through it. The tests below fix
the rule itself, then check each caller against the same fixture, so a caller
that grows its own inlined copy again disagrees with a test rather than with
the other callers.

The archived clause is the one that used to differ. Bulk copy read `archived_at`
as a timestamp a month could sit before — a fund archived after the source
month's end still counted as active in it — while the dashboard and the service
read archiving as global. Global wins here, and the bulk tests pin what that
changed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import Fund, FundKind, Transaction, TxType
from app.services.balances import active_funds_in_month, gather_cashflow_inputs

#: The month under test, with a month either side of it to end funds into.
MONTH = date(2026, 3, 1)
NEXT = date(2026, 4, 1)

#: Well before the month, so `created_at` is never the reason a fund is absent.
LONG_AGO = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture()
def db(clean_db):
    from app.db import new_session

    with new_session() as session:
        yield session
        session.rollback()


def _fund(db, name: str, **kwargs) -> Fund:
    kwargs.setdefault("created_at", LONG_AGO)
    f = Fund(name=name, kind=FundKind.operational, **kwargs)
    db.add(f)
    db.flush()
    return f


def _names(funds) -> list[str]:
    return [f.name for f in funds]


def test_a_fund_created_mid_month_is_active_in_it(db):
    """Created before the month ends, not before it starts — the fund exists
    for part of the month, and a month it exists in any of is a month it shows
    in."""
    _fund(db, "Mid-March", created_at=datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert _names(active_funds_in_month(db, MONTH)) == ["Mid-March"]


def test_a_fund_created_after_the_month_is_not_active_in_it(db):
    _fund(db, "April", created_at=datetime(2026, 4, 2, tzinfo=timezone.utc))
    assert active_funds_in_month(db, MONTH) == []


def test_a_fund_archived_mid_month_is_not_active_in_it(db):
    """Archiving is global, so it applies to the month it happened in too."""
    _fund(db, "Archived", archived_at=datetime(2026, 3, 15, tzinfo=timezone.utc))
    assert active_funds_in_month(db, MONTH) == []


def test_a_fund_archived_after_the_month_is_not_active_in_it_either(db):
    """The resolved disagreement.

    Bulk copy used to count this fund as active in March because it was still
    unarchived when March ended. It no longer does: an archived fund is gone
    from every month, which is what every other total in the app already
    assumed.
    """
    _fund(db, "Archived Later", archived_at=datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert active_funds_in_month(db, MONTH) == []


def test_a_fund_ended_before_the_month_is_not_active_in_it(db):
    """`effective_to_month` in the past — "deleted from April forward" seen
    from May."""
    _fund(db, "Ended in March", effective_to_month=date(2026, 3, 31))
    assert active_funds_in_month(db, NEXT) == []


def test_a_fund_ended_after_this_month_is_still_active_in_it(db):
    """The other side of the same clause: ending a fund from April leaves
    March — and every month before it — intact."""
    _fund(db, "Ends After March", effective_to_month=date(2026, 3, 31))
    assert _names(active_funds_in_month(db, MONTH)) == ["Ends After March"]


def test_active_funds_come_back_in_display_order(db):
    _fund(db, "Third", sort_order=2)
    _fund(db, "First", sort_order=0)
    _fund(db, "Second", sort_order=1)
    assert _names(active_funds_in_month(db, MONTH)) == ["First", "Second", "Third"]


# --- the callers -----------------------------------------------------------


@pytest.fixture()
def mixed_funds(db) -> dict[str, Fund]:
    """One fund of every shape the predicate decides on, all in one database."""
    made = {
        "visible": _fund(db, "Groceries"),
        "new": _fund(db, "Mid-March", created_at=datetime(2026, 3, 15, tzinfo=timezone.utc)),
        "later": _fund(db, "Archived in May", archived_at=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        "archived": _fund(db, "Archived in March", archived_at=datetime(2026, 3, 15, tzinfo=timezone.utc)),
        "ended": _fund(db, "Ended in February", effective_to_month=date(2026, 2, 28)),
    }
    db.commit()
    return made


#: What the predicate says about `mixed_funds` in March — every caller below
#: has to agree with this list.
ACTIVE_IN_MARCH = ["Groceries", "Mid-March"]


def test_the_dashboard_shows_the_active_funds(client, mixed_funds):
    body = client.get("/dashboard", params={"month": "2026-03"}).json()
    assert [f["name"] for f in body["funds"]] == ACTIVE_IN_MARCH


def test_the_cashflow_projector_charges_the_active_funds(db, mixed_funds):
    """The projector reads the same set.

    It only gathers months from the current one forward — a month already over
    is answered from liquid cash alone — so this asks for the current month,
    where the fixture's archived and ended funds are just as absent as they are
    in March.
    """
    month = date.today().replace(day=1)
    inputs = gather_cashflow_inputs(db, month)
    assert [c.name for c in inputs.months[-1].funds] == ACTIVE_IN_MARCH


def test_bulk_copy_copies_the_active_funds(client, db, mixed_funds):
    """Copying March forward moves exactly the funds March shows."""
    for fund in (mixed_funds["visible"], mixed_funds["new"], mixed_funds["later"]):
        db.add(
            Transaction(
                fund_id=fund.id,
                type=TxType.assignment,
                amount=Decimal("100.00"),
                date=date(2026, 3, 10),
            )
        )
    db.commit()

    body = client.post(
        "/bulk/copy-assignments", json={"from_month": "2026-03", "to_month": "2026-04"}
    ).json()

    assert body["funds_updated"] == len(ACTIVE_IN_MARCH)
    assert Decimal(body["total_moved"]) == Decimal("200.00")
    assert [f["name"] for f in client.get("/dashboard", params={"month": "2026-04"}).json()["funds"]] == ACTIVE_IN_MARCH


def test_bulk_copy_no_longer_resurrects_an_archived_fund(client, db, mixed_funds):
    """The behaviour change. A fund archived after March ended used to come
    back — unarchived, and carrying March's assignment into April."""
    later = mixed_funds["later"]
    db.add(
        Transaction(
            fund_id=later.id,
            type=TxType.assignment,
            amount=Decimal("100.00"),
            date=date(2026, 3, 10),
        )
    )
    db.commit()

    body = client.post(
        "/bulk/copy-assignments", json={"from_month": "2026-03", "to_month": "2026-04"}
    ).json()

    assert body["funds_resurrected"] == 0
    db.expire_all()
    assert db.get(Fund, later.id).archived_at is not None
    assert client.get(f"/funds/{later.id}").json()["assigned_this_month"] == "0"


def test_bulk_copy_still_reinstates_a_fund_ended_from_the_target_month(client, db):
    """Unchanged, and deliberately so: `effective_to_month` is the month-scoped
    ending, so a fund that is active in the source month and merely ended
    before the target one is exactly what copying forward is meant to bring
    back."""
    fund = _fund(db, "Rent", effective_to_month=date(2026, 3, 31))
    db.add(
        Transaction(
            fund_id=fund.id,
            type=TxType.assignment,
            amount=Decimal("1800.00"),
            date=date(2026, 3, 1),
        )
    )
    db.commit()

    body = client.post(
        "/bulk/copy-assignments", json={"from_month": "2026-03", "to_month": "2026-04"}
    ).json()

    assert body["funds_resurrected"] == 1
    db.expire_all()
    assert db.get(Fund, fund.id).effective_to_month is None
    assert [f["name"] for f in client.get("/dashboard", params={"month": "2026-04"}).json()["funds"]] == ["Rent"]
