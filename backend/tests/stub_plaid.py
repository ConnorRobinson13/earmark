"""A stub Plaid adapter: the `PlaidClient` port answering from a script.

The sync's rules — the floor date, pending skipping, deduplication, investment
suppression, removed reconciliation, cursor advancement — are the most intricate
logic in the backend and none of it needs a real Plaid. Handing the service one
of these instead of `PlaidApiClient` exercises all of it against transactions
written as literals in the test.

Sync pages are keyed by the cursor that asks for them, so a multi-page sync is
described by chaining them: `{"": page_one, "cursor-1": page_two}`.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.plaid_client import LinkedItem, SyncPage


class StubPlaidClient:
    """Canned Plaid responses. Every call is recorded on `calls` for assertions.

    `accounts_error` makes the accounts fetch raise, which is how the link flow
    gets tested for atomicity — the failure has to land after the Item exists in
    Plaid but before we could possibly have its accounts.
    """

    def __init__(
        self,
        *,
        accounts: list[dict[str, Any]] | None = None,
        pages: dict[str, SyncPage] | None = None,
        linked_item: LinkedItem | None = None,
        link_token: str = "link-sandbox-stub",
        accounts_error: Exception | None = None,
    ) -> None:
        self.accounts_response = accounts if accounts is not None else []
        self.pages = pages or {}
        self.linked_item = linked_item or LinkedItem(
            item_id="item-stub", access_token="access-stub"
        )
        self.link_token = link_token
        self.accounts_error = accounts_error
        self.calls: list[tuple[str, Any]] = []

    def create_link_token(self) -> str:
        self.calls.append(("create_link_token", None))
        return self.link_token

    def exchange_public_token(self, public_token: str) -> LinkedItem:
        self.calls.append(("exchange_public_token", public_token))
        return self.linked_item

    def accounts(self, access_token: str) -> list[dict[str, Any]]:
        self.calls.append(("accounts", access_token))
        if self.accounts_error is not None:
            raise self.accounts_error
        return list(self.accounts_response)

    def sync_transactions(self, access_token: str, cursor: str) -> SyncPage:
        self.calls.append(("sync_transactions", cursor))
        # An unscripted cursor means "nothing further" — the natural end of a
        # sync, so a test only has to write the pages it cares about.
        return self.pages.get(cursor, SyncPage(next_cursor=cursor, has_more=False))


def plaid_account(
    account_id: str,
    *,
    name: str = "Stub Checking",
    type_: str = "depository",
    subtype: str = "checking",
    available: float | None = None,
    current: float = 0.0,
) -> dict[str, Any]:
    """An account shaped the way `/accounts/get` returns them."""
    return {
        "account_id": account_id,
        "name": name,
        "official_name": None,
        "type": type_,
        "subtype": subtype,
        "balances": {"available": available, "current": current},
    }


def plaid_transaction(
    transaction_id: str,
    *,
    txn_date: date,
    amount: float = 10.0,
    merchant_name: str | None = "Stub Merchant",
    account_id: str = "plaid-acct-1",
    pending: bool = False,
) -> dict[str, Any]:
    """A transaction shaped the way `/transactions/sync` returns them."""
    return {
        "transaction_id": transaction_id,
        "account_id": account_id,
        "date": txn_date,
        "amount": amount,
        "merchant_name": merchant_name,
        "name": merchant_name or "Stub",
        "pending": pending,
    }
