"""Balance computation for funds and the unassigned pool.

All "this month" helpers accept an explicit `month` (any date in the target month);
when omitted they default to today's month. This lets the dashboard time-travel
backward (historical snapshots) or forward (planning view) without changing the
underlying data.

A fund's balance is the signed sum of all its transactions through `as_of`
(inclusive). For a past month view we pass as_of = last day of that month so
the balance reflects a historical snapshot.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountType,
    Fund,
    GoalSettlement,
    MonthlyMeta,
    PaydaySchedule,
    Transaction,
)


def month_bounds(d: date) -> tuple[date, date]:
    """Return (first_of_month, first_of_next_month) — last is exclusive upper bound."""
    first = d.replace(day=1)
    if first.month == 12:
        nxt = first.replace(year=first.year + 1, month=1)
    else:
        nxt = first.replace(month=first.month + 1)
    return first, nxt


def days_in_month(d: date) -> int:
    """Number of days in the month containing `d`."""
    return monthrange(d.year, d.month)[1]


def clamp_day_to_month(day: int, d: date) -> date:
    """Return the date in `d`'s month for day-of-month `day`, clamped to the
    month length (e.g. day=31 in February -> the 28th/29th)."""
    first, _ = month_bounds(d)
    return first.replace(day=min(day, days_in_month(first)))


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


def project_cashflow(db: Session, month: date | None = None) -> dict:
    """Day-by-day account-balance projection for every day of the selected month.

    The model is a simple plan: each fund's *full assigned amount* leaves the
    account on its `due_day`, and each payday lands its income on its day. We
    anchor the running balance to reality by working back from current liquid
    cash — the balance shown for *today* equals your real balance now, and the
    days before/after it are reconstructed/projected from that point. Returns one
    entry per day (1st → last) so the UI can render a stacked card per day.
    """
    today = date.today()
    sel_first, sel_nxt = month_bounds(month or today)
    sel_end = sel_nxt - timedelta(days=1)

    current_liquid = liquid_cash(db)

    # Past month: we can't reconstruct historical daily balances meaningfully.
    if sel_end < today:
        return {
            "month": sel_first.isoformat(),
            "past": True,
            "today": today.isoformat(),
            "start_balance": str(current_liquid),
            "ending_balance": str(current_liquid),
            "min_balance": str(current_liquid),
            "min_date": today.isoformat(),
            "goes_negative": False,
            "days": [],
        }

    paydays = list(db.scalars(select(PaydaySchedule)).all())

    # Build every event (full fund amount on its due day, paycheck on its payday)
    # for each month from the current month through the selected one — including
    # dates already past, since we render the whole month and anchor to today.
    events: list[dict] = []
    span_first, _ = month_bounds(today)
    m = span_first
    while m <= sel_first:
        planned = planned_income_for_month(db, m)
        fixed_total = sum((p.amount for p in paydays if p.amount is not None), Decimal("0"))
        split_count = sum(1 for p in paydays if p.amount is None)
        split_each = (planned - fixed_total) / split_count if split_count else Decimal("0")
        for p in paydays:
            amt = p.amount if p.amount is not None else split_each
            if amt == 0:
                continue
            events.append(
                {
                    "date": clamp_day_to_month(p.day_of_month, m),
                    "kind": "income",
                    "label": "Paycheck",
                    "amount": Decimal(amt),
                }
            )
        for f in active_funds_in_month(db, m):
            assigned = fund_assigned_in_month(db, f.id, m)
            if assigned == 0:
                continue
            events.append(
                {
                    "date": clamp_day_to_month(f.due_day, m),
                    "kind": "outflow",
                    "label": f.name,
                    "amount": -Decimal(assigned),
                }
            )
        m = month_bounds(m)[1]

    events.sort(key=lambda e: e["date"])

    # Anchor: pick the balance carried into the start of the span so that the
    # running balance on `today` equals current liquid cash.
    #   balance(today) = span_start + Σ(events dated ≤ today)  ==  current_liquid
    consumed = sum((e["amount"] for e in events if e["date"] <= today), Decimal("0"))
    span_start = current_liquid - consumed

    # Walk the whole span day by day; keep only the selected month's days.
    days: list[dict] = []
    running = span_start
    carried_in = span_start  # balance carried into the first selected day
    min_balance: Decimal | None = None
    min_date = sel_first
    ei = 0
    d = span_first
    while d <= sel_end:
        if d == sel_first:
            carried_in = running
        day_events = []
        while ei < len(events) and events[ei]["date"] == d:
            running += events[ei]["amount"]
            day_events.append(
                {
                    "kind": events[ei]["kind"],
                    "label": events[ei]["label"],
                    "amount": str(events[ei]["amount"]),
                }
            )
            ei += 1
        if d >= sel_first:
            days.append(
                {
                    "date": d.isoformat(),
                    "balance": str(running),
                    "events": day_events,
                    "is_today": d == today,
                }
            )
            if min_balance is None or running < min_balance:
                min_balance = running
                min_date = d
        d += timedelta(days=1)

    start_balance = str(carried_in)
    min_balance = min_balance if min_balance is not None else span_start

    return {
        "month": sel_first.isoformat(),
        "past": False,
        "today": today.isoformat(),
        "start_balance": start_balance,
        "ending_balance": str(running),
        "min_balance": str(min_balance),
        "min_date": min_date.isoformat(),
        "goes_negative": min_balance < 0,
        "days": days,
    }


def enrich_fund(db: Session, f: Fund, month: date | None = None) -> dict:
    month = month or date.today()
    _, nxt = month_bounds(month)
    as_of = nxt - timedelta(days=1)  # last day of selected month
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
