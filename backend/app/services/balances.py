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

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..cashflow import CashflowInputs, FundCharge, MonthInputs, Payday
from ..month import (
    current_month,
    first_of_month,
    last_day_of_month,
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


def fund_net_spent_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Net outflows for a fund within `month`, positive when net spent.

    Includes expense, transfer, AND tagged income — so reimbursements offset spending.
    Assignments are excluded since they are budgeting, not spending.
    """
    first, nxt = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date >= first,
            Transaction.date < nxt,
            Transaction.type.in_(["expense", "transfer", "income"]),
        )
    )
    return -Decimal(total or 0)


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


def fund_balance_at_month_start(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Fund balance carried into `month` (sum of transactions before its first day)."""
    first, _ = month_bounds(month or date.today())
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.fund_id == fund_id,
            Transaction.date < first,
        )
    )
    return Decimal(total or 0)


def fund_available_in_month(db: Session, fund_id: int, month: date | None = None) -> Decimal:
    """Rollover + this month's assignment."""
    return fund_balance_at_month_start(db, fund_id, month) + fund_assigned_in_month(
        db, fund_id, month
    )


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


def goal_contributions_in_year(db: Session, goal_id: int, year: int) -> Decimal:
    """Sum of GoalSettlements for `goal_id` whose settled_at falls in `year`.
    This is the right metric for contribution goals (Roth/HSA/401k) — what
    matters is how much money you physically moved into the account this tax
    year, not the account's current market value."""
    total = db.scalar(
        select(func.coalesce(func.sum(GoalSettlement.amount), 0)).where(
            GoalSettlement.goal_id == goal_id,
            GoalSettlement.settled_at >= date(year, 1, 1),
            GoalSettlement.settled_at < date(year + 1, 1, 1),
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
    """Funds visible in `month` — same rule the dashboard uses: not archived,
    created before the month ends, and not ended before the month starts."""
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


def gather_cashflow_inputs(
    db: Session, month: date | None = None, today: date | None = None
) -> CashflowInputs:
    """Read everything `app.cashflow.project` needs to project `month`.

    This is the database half of the cash-flow projection, and the only half
    that touches a session: current liquid cash, the payday schedule, and — for
    every month from the current one through the selected one — that month's
    planned income and the funds drawing on it. The span reaches back to the
    current month because the projection anchors its running balance to today's
    real cash and carries it forward from there.
    """
    today = today or date.today()
    sel_first = first_of_month(month or today)
    current_liquid = liquid_cash(db)

    # A month already over is answered from liquid cash alone, so don't pay for
    # per-month reads the projection will never look at.
    if last_day_of_month(sel_first) < today:
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


def enrich_fund(db: Session, f: Fund, month: date | None = None) -> dict:
    month = month or date.today()
    as_of = last_day_of_month(month)
    out = {
        "id": f.id,
        "name": f.name,
        "kind": f.kind,
        "target": f.target,
        "target_date": f.target_date,
        "goal_type": f.goal_type,
        "backed_by_account_id": f.backed_by_account_id,
        "min_payment": f.min_payment,
        "sort_order": f.sort_order,
        "category": f.category,
        "due_day": f.due_day,
        "archived_at": f.archived_at,
        "balance": fund_balance(db, f.id, as_of=as_of),
        "net_spent_this_month": fund_net_spent_in_month(db, f.id, month),
        "assigned_this_month": fund_assigned_in_month(db, f.id, month),
        "available_this_month": fund_available_in_month(db, f.id, month),
        "contribution_ytd": None,
        "contribution_year": None,
    }
    # For contribution goals: year = year of target_date if set, else the
    # viewed month's year. YTD = sum of GoalSettlements within that year.
    if f.goal_type and f.goal_type.value == "contribution":
        year = f.target_date.year if f.target_date else month.year
        out["contribution_year"] = year
        out["contribution_ytd"] = goal_contributions_in_year(db, f.id, year)
    return out
