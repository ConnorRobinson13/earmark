from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .models import AccountType, FundKind, InboxStatus, TxType


# ---------- Funds ----------

class FundBase(BaseModel):
    name: str
    kind: FundKind = FundKind.operational
    target: Optional[Decimal] = None
    target_date: Optional[date] = None
    backed_by_account_id: Optional[int] = None
    sort_order: int = 0
    category: Optional[str] = None


class FundCreate(FundBase):
    pass


class FundUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[FundKind] = None
    target: Optional[Decimal] = None
    target_date: Optional[date] = None
    backed_by_account_id: Optional[int] = None
    sort_order: Optional[int] = None
    category: Optional[str] = None
    archived: Optional[bool] = None


class FundOut(FundBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    balance: Decimal = Decimal("0")
    net_spent_this_month: Decimal = Decimal("0")
    assigned_this_month: Decimal = Decimal("0")
    available_this_month: Decimal = Decimal("0")
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


# ---------- Dashboard ----------

class DashboardOut(BaseModel):
    liquid_total: Decimal
    credit_owed: Decimal
    net_cash: Decimal
    unassigned: Decimal
    funds_total: Decimal       # sum of fund balances at end of month — "left to spend safely"
    spent_this_month: Decimal  # sum of net_spent across funds for selected month
    income_this_month: Decimal # sum of untagged income for selected month
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
