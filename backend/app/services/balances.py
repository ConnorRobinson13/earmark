"""Balance computation for funds and the unassigned pool.

All "this month" helpers accept an explicit `month` (any date in the target month);
when omitted they default to today's month. This lets the dashboard time-travel
backward (historical snapshots) or forward (planning view) without changing the
underlying data.

A fund's balance is the signed sum of all its transactions through `as_of`
(inclusive). For a past month view we pass as_of = last day of that month so
the balance reflects a historical snapshot.

Month arithmetic — bounds, last day, day clamping — lives in `app.month`; this
module only uses it.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..month import (
    current_month,
    first_of_month,
    month_bounds,
    next_month,
)
from ..models import (
    Account,
    AccountType,
    Fund,
    GoalSettlement,
    MonthlyMeta,
    PaydaySchedule,
    Transaction,
)
from .cashflow import CashflowInputs, FundCharge, MonthInputs, Payday, month_is_over


def liquid_cash(db: Session) -> Decimal:
    """Spendable cash = live checking + savings balances. Emergency-fund and
    investment accounts are excluded (earmarked / long-term); credit is debt."""
    total = db.scalar(
        select(func.coalesce(func.sum(Account.current_balance), 0)).where(
            Account.type.in_([AccountType.checking, AccountType.savings])
        )
    )
    return Decimal(total or 0)


def fund_balance(db: Session, fund_id: int, as_of: date | None = None) -> Decimal:
    q = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.fund_id == fund_id
    )
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    return Decimal(db.scalar(q) or 0)


def fund_assigned_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Sum of assignment entries on this fund within `month`."""
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type == "assignment",
        )
    )
    return Decimal(total or 0)


def untagged_income_in_month(db: Session, month: date | None = None) -> Decimal:
    """Total actual income received this month so far (untagged), capped at
    today. Future-dated transactions don't count as "received" yet — they're
    expected, not realized. Informational: doesn't drive Unassigned in the
    EveryDollar-style model, just lets the card show plan-vs-actual progress."""
    first, nxt = month_bounds(month or date.today())
    today = date.today()
    upper = min(nxt, today + timedelta(days=1))  # exclusive upper bound
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id.is_(None),
            Transaction.type == "income",
            Transaction.date >= first,
            Transaction.date < upper,
        )
    )
    return Decimal(total or 0)


def planned_income_for_month(db: Session, month: date) -> Decimal:
    first, _ = month_bounds(month)
    row = db.get(MonthlyMeta, first)
    return Decimal(row.planned_income) if row else Decimal("0")


def assignments_into_funds_through(db: Session, as_of: date) -> Decimal:
    """Sum of all assignment amounts credited to funds (fund_id IS NOT NULL)
    on or before `as_of`. These are the only thing that reduces Unassigned in
    the EveryDollar-style model."""
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id.is_not(None),
            Transaction.type == "assignment",
            Transaction.date <= as_of,
        )
    )
    return Decimal(total or 0)


def planned_income_through(db: Session, as_of: date) -> Decimal:
    """Sum of planned_income across all months whose first day is <= as_of."""
    total = db.scalar(
        select(func.coalesce(func.sum(MonthlyMeta.planned_income), 0)).where(
            MonthlyMeta.month <= as_of,
        )
    )
    return Decimal(total or 0)


def unassigned_balance(db: Session, as_of: date | None = None) -> Decimal:
    """EveryDollar-style: Unassigned = cumulative planned income − cumulative
    assignments to funds, through `as_of`. Actual deposits do NOT factor in —
    they were already allocated against the planned figure."""
    as_of = as_of or date.today()
    return planned_income_through(db, as_of) - assignments_into_funds_through(db, as_of)


def gross_spent_in_month(db: Session, month: date | None = None) -> Decimal:
    """Net spending on operational funds for `month`, positive.

    Includes expense + transfer + income on operational funds, so reimbursements
    (roommate Zelles, etc.) offset outflows. Goals are excluded entirely so
    bookkeeping inflows like "Starting balance" or "Auto-sync from <account>"
    don't distort the headline.
    """
    from ..models import FundKind  # local import — avoids reshuffling top-level
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Fund, Fund.id == Transaction.fund_id)
        .where(
            Fund.kind == FundKind.operational,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type.in_(["expense", "transfer", "income"]),
        )
    )
    return -Decimal(total or 0)


def spend_by_category_in_month(db: Session, month: date | None = None) -> dict[str, Decimal]:
    """Net spend per operational-fund category for `month`, positive when spent.

    Same inclusion rule as `gross_spent_in_month` (expense + transfer + income so
    reimbursements offset), but grouped by `Fund.category`. Goals are excluded.
    Funds with no category roll up under "Uncategorized".
    """
    from ..models import FundKind  # local import — avoids reshuffling top-level
    first, nxt = month_bounds(month or date.today())
    rows = db.execute(
        select(Fund.category, func.coalesce(func.sum(Transaction.amount), 0))
        .join(Fund, Fund.id == Transaction.fund_id)
        .where(
            Fund.kind == FundKind.operational,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type.in_(["expense", "transfer", "income"]),
        )
        .group_by(Fund.category)
    ).all()
    return {(cat or "Uncategorized"): -Decimal(total or 0) for cat, total in rows}


def goals_saved_in_month(db: Session, month: date | None = None) -> Decimal:
    """Money actually moved into goal-backing accounts in `month`, positive.

    Reads from the `goal_settlements` table — i.e. only counts savings the user
    has explicitly marked as "moved" via the To-Move panel. Earmarked-but-not-
    yet-moved sits in pending; see `goal_pending_settlement`.
    """
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(GoalSettlement.amount), 0)).where(
            GoalSettlement.settled_at >= first,
            GoalSettlement.settled_at < nxt,
        )
    )
    return Decimal(total or 0)


def goal_pending_settlement(db: Session, goal_id: int, month: date | None = None) -> Decimal:
    """For a goal, how much was assigned this month but not yet moved to its account."""
    first, nxt = month_bounds(month or date.today())
    assigned = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == goal_id,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type == "assignment",
        )
    )
    settled = db.scalar(
        select(func.coalesce(func.sum(GoalSettlement.amount), 0)).where(
            GoalSettlement.goal_id == goal_id,
            GoalSettlement.settled_at >= first,
            GoalSettlement.settled_at < nxt,
        )
    )
    return Decimal(assigned or 0) - Decimal(settled or 0)


def all_funds_total(db: Session, as_of: date | None = None) -> Decimal:
    # Only money sitting in *active* funds counts toward the headline. Archived
    # funds are excluded: real ones sweep to 0 on archive (no effect), and the
    # hidden "[History]" funds holding imported EveryDollar history must never
    # distort current state.
    q = (
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Fund, Fund.id == Transaction.fund_id)
        .where(Fund.archived_at.is_(None))
    )
    if as_of is not None:
        q = q.where(Transaction.date <= as_of)
    return Decimal(db.scalar(q) or 0)


def active_funds_in_month(db: Session, month: date) -> list[Fund]:
    """Every fund visible in `month`, in display order.

    The one definition of "active in a month": the dashboard, the bulk copy,
    the cash-flow projection and the pending-settlements list all read the
    month's funds through here, so they cannot answer the question differently.
    A fund is active when all three of these hold.

    *Not archived.* Archiving is global, not month-scoped — it sweeps the
    fund's balance to Unassigned *today* and hides the fund from the funds
    list, the headline totals, net worth and the categoriser alike. So an
    archived fund is gone from past months too, not merely from the ones after
    it was archived. This is the clause the bulk copy used to disagree on: it
    read `archived_at` as a timestamp a month could sit before, which let
    copying assignments forward pick up a fund the user had deleted and bring
    it back. It also risked un-hiding the `[History]` funds the EveryDollar
    import archives on creation, which exist only to hold imported history and
    must never surface.

    *Created before the month ended.* A month a fund existed for any part of
    is a month the fund belongs to.

    *Not already ended when the month began.* `effective_to_month` is the
    month-scoped ending — what "delete from this month forward" sets — and it
    is the only clause that a month can legitimately fall either side of.
    """
    first, nxt = month_bounds(month)
    return list(
        db.scalars(
            select(Fund)
            .where(
                Fund.archived_at.is_(None),
                Fund.created_at < nxt,
                (Fund.effective_to_month.is_(None))
                | (Fund.effective_to_month >= first),
            )
            .order_by(Fund.sort_order, Fund.id)
        ).all()
    )


def gather_cashflow_inputs(db: Session, month: date | None = None) -> CashflowInputs:
    """Read everything `app.services.cashflow.project` needs to project `month`.

    This is the database half of the cash-flow projection, and the only half
    that touches a session: current liquid cash, the payday schedule, and — for
    every month from the current one through the selected one — that month's
    planned income and the funds drawing on it. The span reaches back to the
    current month because the projection anchors its running balance to today's
    real cash and carries it forward from there.
    """
    today = date.today()
    sel_first = first_of_month(month or today)
    current_liquid = liquid_cash(db)

    # A month already over is answered from liquid cash alone, so don't pay for
    # per-month reads the projection will never look at.
    if month_is_over(sel_first, today):
        return CashflowInputs(today=today, month=sel_first, liquid_cash=current_liquid)

    paydays = [
        Payday(day_of_month=p.day_of_month, amount=p.amount)
        for p in db.scalars(select(PaydaySchedule)).all()
    ]

    months: list[MonthInputs] = []
    m = current_month(today)
    while m <= sel_first:
        months.append(
            MonthInputs(
                month=m,
                planned_income=planned_income_for_month(db, m),
                funds=[
                    FundCharge(
                        name=f.name,
                        due_day=f.due_day,
                        assigned=fund_assigned_in_month(db, f.id, m),
                    )
                    for f in active_funds_in_month(db, m)
                ],
            )
        )
        m = next_month(m)

    return CashflowInputs(
        today=today,
        month=sel_first,
        liquid_cash=current_liquid,
        paydays=paydays,
        months=months,
    )


class _FundTotals(NamedTuple):
    """One fund's transactions, summed over the four windows a month needs.

    They are one type because they come from one scan: every figure below is a
    different slice of the same fund's rows, which is exactly why asking for
    them separately was wasteful.
    """

    balance: Decimal      # everything through the end of the month
    carried_in: Decimal   # everything before the month started
    net_flow: Decimal     # signed spending within the month (negative when spent)
    assigned: Decimal     # assignments within the month


_NO_ACTIVITY = _FundTotals(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))

#: What counts as spending for a single fund: tagged income is included so
#: reimbursements offset outflows, and assignments are excluded because they are
#: budgeting rather than spending. `gross_spent_in_month` applies the same three
#: types to the headline figure, but narrowed to operational funds.
_SPENDING_TYPES = ("expense", "transfer", "income")


def _totals_by_fund(
    db: Session, fund_ids: list[int], month: date
) -> dict[int, _FundTotals]:
    """The four windows for every fund in `fund_ids`, in one grouped scan.

    `date < nxt` is the same cut as a per-fund `date <= as_of` with `as_of` the
    last day of the month, so a single bound on the scan serves both the
    end-of-month balance and the in-month windows nested inside it. Funds with
    no transactions simply come back missing; the caller reads them as zero.
    """
    first, nxt = month_bounds(month)
    in_month = Transaction.date >= first
    rows = db.execute(
        select(
            Transaction.fund_id,
            func.coalesce(func.sum(Transaction.amount), 0).label("balance"),
            func.coalesce(
                func.sum(Transaction.amount).filter(Transaction.date < first), 0
            ).label("carried_in"),
            func.coalesce(
                func.sum(Transaction.amount).filter(
                    in_month, Transaction.type.in_(_SPENDING_TYPES)
                ),
                0,
            ).label("net_flow"),
            func.coalesce(
                func.sum(Transaction.amount).filter(
                    in_month, Transaction.type == "assignment"
                ),
                0,
            ).label("assigned"),
        )
        .where(Transaction.fund_id.in_(fund_ids), Transaction.date < nxt)
        .group_by(Transaction.fund_id)
    )
    return {
        row.fund_id: _FundTotals(
            balance=Decimal(row.balance),
            carried_in=Decimal(row.carried_in),
            net_flow=Decimal(row.net_flow),
            assigned=Decimal(row.assigned),
        )
        for row in rows
    }


def _contributions_by_goal(db: Session, years: dict[int, int]) -> dict[int, Decimal]:
    """Settlements for each goal in `years`, summed over that goal's own year.

    `years` maps goal id to the tax year that goal is measured against, and two
    goals can want different years — so the sums come back grouped by goal *and*
    year and each goal then takes its own. One query covers the set.
    """
    if not years:
        return {}

    settled_year = func.extract("year", GoalSettlement.settled_at)
    by_goal_year = {
        (goal_id, int(year)): Decimal(total)
        for goal_id, year, total in db.execute(
            select(
                GoalSettlement.goal_id,
                settled_year.label("year"),
                func.coalesce(func.sum(GoalSettlement.amount), 0),
            )
            .where(
                GoalSettlement.goal_id.in_(list(years)),
                # Bounded by date rather than by the extracted year so the
                # (goal_id, settled_at) index still carries the lookup.
                GoalSettlement.settled_at >= date(min(years.values()), 1, 1),
                GoalSettlement.settled_at < date(max(years.values()) + 1, 1, 1),
            )
            .group_by(GoalSettlement.goal_id, settled_year)
        )
    }
    return {
        goal_id: by_goal_year.get((goal_id, year), Decimal("0"))
        for goal_id, year in years.items()
    }


def enrich_funds(
    db: Session, funds: Sequence[Fund], month: date | None = None
) -> list[schemas.FundOut]:
    """The month's derived figures for every fund in `funds`.

    Plural because the figures are cheaper together than apart. Each fund needs
    a balance, the balance it carried in, its spending and its assignments for
    the month — four windows over the same rows — so asking one fund at a time
    meant re-reading that fund's transactions four times over. Here they are
    four aggregates of a single grouped scan, and contribution goals add one
    more query for the whole set rather than one each. Two statements, whether
    the dashboard is showing four funds or forty.

    The response schema is read off the fund itself rather than copied field by
    field, so a column added to `FundOut` arrives here without an edit — the
    hand-built dict this replaces was a second copy that drifted on its own.
    """
    if not funds:
        return []

    month = month or date.today()
    totals = _totals_by_fund(db, [f.id for f in funds], month)

    # Contribution goals (Roth/HSA/401k) are measured over a tax year, not a
    # month: the year of the target date when there is one, else the year being
    # viewed.
    years = {
        f.id: (f.target_date.year if f.target_date else month.year)
        for f in funds
        if f.goal_type is not None and f.goal_type.value == "contribution"
    }
    contributions = _contributions_by_goal(db, years)

    enriched = []
    for f in funds:
        t = totals.get(f.id, _NO_ACTIVITY)
        enriched.append(
            schemas.FundOut.model_validate(f).model_copy(
                update={
                    "balance": t.balance,
                    # Stored signed, reported positive when money left the fund.
                    "net_spent_this_month": -t.net_flow,
                    "assigned_this_month": t.assigned,
                    "available_this_month": t.carried_in + t.assigned,
                    "contribution_ytd": contributions.get(f.id),
                    "contribution_year": years.get(f.id),
                }
            )
        )
    return enriched
