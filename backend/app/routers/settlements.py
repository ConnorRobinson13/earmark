"""End-of-month settlement: marking goal money as actually moved.

Workflow: at the start of the month the user assigns $X from Unassigned to a
goal (creates an `assignment` Transaction → goal.balance += X). The cash hasn't
physically moved out of checking yet. On the last day of the month they hit
"Mark moved" in the To-Move panel — that posts here, we record a
`GoalSettlement` and adjust the source/destination Account balances.

The goal's fund balance is untouched (it was already credited by the assignment).
`goals_saved_in_month` reads from settlements, so the dashboard's "Saved" tile
only counts money that's been physically moved.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, AccountType, Fund, FundKind, GoalSettlement
from ..month import parse_month_or_current
from ..services import settlements as settlements_svc
from ..services.balances import active_funds_in_month, goal_pending_settlement

router = APIRouter(prefix="/settlements", tags=["settlements"])


class ToMoveItem(BaseModel):
    goal_id: int
    goal_name: str
    pending_amount: Decimal
    to_account_id: int | None
    to_account_name: str | None
    suggested_from_account_id: int | None


class SettleBody(BaseModel):
    amount: Decimal
    from_account_id: int | None = None
    settled_at: date | None = None


@router.get("/pending", response_model=list[ToMoveItem])
def list_pending(month: str | None = None, db: Session = Depends(get_db)):
    """Goals with a positive pending amount for the given month."""
    month_date = parse_month_or_current(month)

    first_checking = db.scalar(
        select(Account).where(Account.type == AccountType.checking).order_by(Account.id).limit(1)
    )
    suggested_from = first_checking.id if first_checking else None

    # Which goals the month shows is the shared question, so it gets the shared
    # answer: a goal ended from an earlier month, or created after this one, is
    # no more settleable here than it is visible on the dashboard. Kind is all
    # this caller narrows by, and it narrows the loaded list rather than the
    # query — a month's funds are few, and a `kind=` argument on the predicate
    # would be one every other caller passes nothing to.
    goals = [f for f in active_funds_in_month(db, month_date) if f.kind == FundKind.goal]

    items: list[ToMoveItem] = []
    for g in goals:
        pending = goal_pending_settlement(db, g.id, month_date)
        if pending <= 0:
            continue
        to_acct = db.get(Account, g.backed_by_account_id) if g.backed_by_account_id else None
        items.append(ToMoveItem(
            goal_id=g.id,
            goal_name=g.name,
            pending_amount=pending,
            to_account_id=to_acct.id if to_acct else None,
            to_account_name=to_acct.name if to_acct else None,
            suggested_from_account_id=suggested_from,
        ))
    return items


@router.post("/goal/{goal_id}", status_code=201)
def settle_goal(goal_id: int, body: SettleBody, db: Session = Depends(get_db)):
    """Record that `amount` was moved from `from_account_id` to the goal's
    backing account. The balance movement itself lives in the settlements
    service, which is also what undoes it."""
    goal = db.get(Fund, goal_id)
    if not goal or goal.kind != FundKind.goal:
        raise HTTPException(404, "Goal not found")

    settled_at = body.settled_at or date.today()
    try:
        s = settlements_svc.settle_goal(
            db,
            goal=goal,
            amount=body.amount,
            settled_at=settled_at,
            from_account_id=body.from_account_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Read the row before committing — commit expires it, and re-reading these
    # few fields would cost another SELECT.
    response = {
        "id": s.id,
        "goal_id": goal.id,
        "amount": str(body.amount),
        "from_account_id": s.from_account_id,
        "to_account_id": s.to_account_id,
        "settled_at": settled_at.isoformat(),
    }
    db.commit()
    return response


@router.delete("/{settlement_id}", status_code=204)
def undo_settlement(settlement_id: int, db: Session = Depends(get_db)):
    s = db.get(GoalSettlement, settlement_id)
    if not s:
        raise HTTPException(404)
    settlements_svc.unsettle(db, s)
    db.commit()
