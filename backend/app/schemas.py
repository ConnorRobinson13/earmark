from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import AccountType, FundKind, GoalType, InboxStatus, TxType


# ---------- Funds ----------

class FundBase(BaseModel):
    name: str
    kind: FundKind = FundKind.operational
    target: Optional[Decimal] = None
    target_date: Optional[date] = None
    goal_type: Optional[GoalType] = None  # set only when kind=goal
    backed_by_account_id: Optional[int] = None
    min_payment: Optional[Decimal] = None  # debt funds: fixed monthly payment
    sort_order: int = 0
    category: Optional[str] = None
    due_day: int = Field(default=1, ge=1, le=31)  # day-of-month the bill is due


class FundCreate(FundBase):
    pass


class FundUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[FundKind] = None
    target: Optional[Decimal] = None
    target_date: Optional[date] = None
    goal_type: Optional[GoalType] = None
    backed_by_account_id: Optional[int] = None
    min_payment: Optional[Decimal] = None
    sort_order: Optional[int] = None
    category: Optional[str] = None
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    archived: Optional[bool] = None


class FundOut(FundBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    balance: Decimal = Decimal("0")
    net_spent_this_month: Decimal = Decimal("0")
    assigned_this_month: Decimal = Decimal("0")
    available_this_month: Decimal = Decimal("0")
    contribution_ytd: Optional[Decimal] = None    # contribution goals only
    contribution_year: Optional[int] = None       # contribution goals only
    archived_at: Optional[datetime] = None


# ---------- Transactions ----------

class TransactionBase(BaseModel):
    type: TxType
    amount: Decimal  # signed
    date: date
    merchant: str = ""
    notes: Optional[str] = None
    fund_id: Optional[int] = None


class TransactionCreate(TransactionBase):
    pass


class TransactionOut(TransactionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    linked_transaction_id: Optional[int] = None
    plaid_transaction_id: Optional[str] = None
    created_at: datetime


class TransferCreate(BaseModel):
    from_fund_id: int
    to_fund_id: int
    amount: Decimal = Field(gt=0)
    date: date
    notes: Optional[str] = None


class AssignmentCreate(BaseModel):
    """Move money between Unassigned pool and a fund.

    Positive amount: Unassigned -> fund. Negative: fund -> Unassigned (un-assign).
    """

    fund_id: int
    amount: Decimal
    date: date
    notes: Optional[str] = None


class QuickAddCreate(BaseModel):
    """Convenience endpoint: positive amount, type=expense by default.

    fund_id is optional only when type=income — untagged income lands in Unassigned.
    """

    fund_id: Optional[int] = None
    amount: Decimal = Field(gt=0)
    date: date
    merchant: str = ""
    notes: Optional[str] = None
    type: TxType = TxType.expense


# ---------- Accounts ----------

class AccountBase(BaseModel):
    name: str
    type: AccountType
    current_balance: Decimal = Decimal("0")


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    """All fields optional — PATCH-friendly partial updates."""
    name: Optional[str] = None
    type: Optional[AccountType] = None
    current_balance: Optional[Decimal] = None


class AccountOut(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    last_synced_at: Optional[datetime] = None


# ---------- Templates ----------

class TemplateItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[int] = None
    fund_id: int
    planned_amount: Decimal


class TemplateApply(BaseModel):
    month: date  # any date in target month


# ---------- Paydays ----------

class PaydayCreate(BaseModel):
    day_of_month: int = Field(ge=1, le=31)
    amount: Optional[Decimal] = None  # NULL -> even split of planned income


class PaydayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    day_of_month: int
    amount: Optional[Decimal] = None


# ---------- Inbox ----------

class InboxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    merchant: str
    amount: Decimal
    date: date
    suggested_fund_id: Optional[int]
    status: InboxStatus
    created_at: datetime


class InboxApprove(BaseModel):
    fund_id: Optional[int] = None  # override suggestion
    as_paycheck: bool = False      # income-only: post as untagged paycheck (no fund)


# ---------- Dashboard ----------

class DashboardOut(BaseModel):
    liquid_total: Decimal
    credit_owed: Decimal
    net_cash: Decimal
    unassigned: Decimal
    funds_total: Decimal       # sum of fund balances at end of month — "left to spend safely"
    spent_this_month: Decimal   # net operational outflows (reimbursements offset)
    saved_this_month: Decimal   # active contributions to goals (excludes bookkeeping)
    income_this_month: Decimal  # actual untagged income received this month
    planned_income: Decimal     # target income for this month (EveryDollar-style)
    month: str                 # ISO date of the first day of the selected month
    funds: list[FundOut]


# ---------- Suggestion ----------

class SuggestRequest(BaseModel):
    merchant: str
    amount: Optional[Decimal] = None


class SuggestResponse(BaseModel):
    fund_id: Optional[int]
    fund_name: Optional[str]
    source: str  # "vector" | "llm" | "none"
