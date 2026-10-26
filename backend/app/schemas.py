from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from .models import AccountType, FundKind, GoalType, InboxStatus, TxType

# ---------- Funds ----------


class FundBase(BaseModel):
    name: str
    kind: FundKind = FundKind.operational
    target: Decimal | None = None
    target_date: date | None = None
    goal_type: GoalType | None = None  # set only when kind=goal
    backed_by_account_id: int | None = None
    min_payment: Decimal | None = None  # debt funds: fixed monthly payment
    sort_order: int = 0
    category: str | None = None
    due_day: int = Field(default=1, ge=1, le=31)  # day-of-month the bill is due


class FundCreate(FundBase):
    pass


class FundUpdate(BaseModel):
    name: str | None = None
    kind: FundKind | None = None
    target: Decimal | None = None
    target_date: date | None = None
    goal_type: GoalType | None = None
    backed_by_account_id: int | None = None
    min_payment: Decimal | None = None
    sort_order: int | None = None
    category: str | None = None
    due_day: int | None = Field(default=None, ge=1, le=31)
    archived: bool | None = None


class FundOut(FundBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    balance: Decimal = Decimal("0")
    net_spent_this_month: Decimal = Decimal("0")
    assigned_this_month: Decimal = Decimal("0")
    available_this_month: Decimal = Decimal("0")
    contribution_ytd: Decimal | None = None  # contribution goals only
    contribution_year: int | None = None  # contribution goals only
    archived_at: datetime | None = None


# ---------- Transactions ----------


class TransactionBase(BaseModel):
    type: TxType
    amount: Decimal  # signed
    date: date
    merchant: str = ""
    notes: str | None = None
    fund_id: int | None = None


class TransactionCreate(TransactionBase):
    pass


class TransactionOut(TransactionBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    linked_transaction_id: int | None = None
    plaid_transaction_id: str | None = None
    created_at: datetime


class TransferCreate(BaseModel):
    from_fund_id: int
    to_fund_id: int
    amount: Decimal = Field(gt=0)
    date: date
    notes: str | None = None


class AssignmentCreate(BaseModel):
    """Move money between Unassigned pool and a fund.

    Positive amount: Unassigned -> fund. Negative: fund -> Unassigned (un-assign).
    """

    fund_id: int
    amount: Decimal
    date: date
    notes: str | None = None


class TransactionMove(BaseModel):
    """Re-tag an already-assigned transaction to a different fund."""

    fund_id: int


class QuickAddCreate(BaseModel):
    """Convenience endpoint: positive amount, type=expense by default.

    fund_id is optional only when type=income — untagged income lands in Unassigned.
    """

    fund_id: int | None = None
    amount: Decimal = Field(gt=0)
    date: date
    merchant: str = ""
    notes: str | None = None
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

    name: str | None = None
    type: AccountType | None = None
    current_balance: Decimal | None = None


class AccountOut(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    last_synced_at: datetime | None = None


# ---------- Paydays ----------


class PaydayCreate(BaseModel):
    day_of_month: int = Field(ge=1, le=31)
    amount: Decimal | None = None  # NULL -> even split of planned income


class PaydayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    day_of_month: int
    amount: Decimal | None = None


# ---------- Inbox ----------


class InboxItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    merchant: str
    amount: Decimal
    date: date
    suggested_fund_id: int | None
    status: InboxStatus
    created_at: datetime


class InboxApprove(BaseModel):
    fund_id: int | None = None  # override suggestion
    as_paycheck: bool = False  # income-only: post as untagged paycheck (no fund)


# ---------- Dashboard ----------


class DashboardOut(BaseModel):
    liquid_total: Decimal
    credit_owed: Decimal
    net_cash: Decimal
    unassigned: Decimal
    funds_total: (
        Decimal  # sum of fund balances at end of month — "left to spend safely"
    )
    spent_this_month: Decimal  # net operational outflows (reimbursements offset)
    saved_this_month: Decimal  # active contributions to goals (excludes bookkeeping)
    income_this_month: Decimal  # actual untagged income received this month
    planned_income: Decimal  # target income for this month (EveryDollar-style)
    month: str  # ISO date of the first day of the selected month
    funds: list[FundOut]


# ---------- Suggestion ----------


class SuggestRequest(BaseModel):
    merchant: str
    amount: Decimal | None = None


class SuggestResponse(BaseModel):
    fund_id: int | None
    fund_name: str | None
    source: str  # "vector" | "llm" | "none"


# ---------- AI auto-sort ----------


class AutosortStatus(BaseModel):
    enabled: bool  # whether OPENROUTER_API_KEY is configured
    model: str  # the pinned OpenRouter model id


class AutosortSuggestion(BaseModel):
    """A proposed fund for one unassigned transaction. Advisory only — no
    assignment changes until the caller confirms it."""

    transaction_id: int
    merchant: str
    amount: Decimal
    date: date
    current_fund_id: int | None = None
    suggested_fund_id: int
    suggested_fund_name: str


class AutosortSuggestResponse(BaseModel):
    suggestions: list[AutosortSuggestion]


class AutosortChange(BaseModel):
    transaction_id: int
    fund_id: int


class AutosortConfirmRequest(BaseModel):
    """The explicit confirmation step: the subset of suggestions the user
    accepted. Nothing is written for a transaction that isn't listed here."""

    changes: list[AutosortChange]


class AutosortConfirmResponse(BaseModel):
    updated: list[TransactionOut]
