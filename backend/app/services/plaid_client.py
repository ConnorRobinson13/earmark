"""The Plaid port: what this application actually needs from Plaid, and the
SDK-backed adapter that supplies it.

Four calls, plain dicts and small frozen results — that is the whole surface.
Everything the SDK insists on (request model classes, an `ApiClient` built from
configuration, responses that index like dicts but hold enum and `date` objects)
stops here, so no caller has to import `plaid` to talk to Plaid. Handlers take a
`PlaidClient` by dependency injection rather than constructing one, which is what
lets the tests drive the entire sync from a stub with no SDK and no sandbox
account (see `tests/stub_plaid.py`).

Account and transaction payloads stay as the dicts Plaid sent, because the sync
stores the raw transaction verbatim and reads accounts with `.get` — reshaping
them here would only invent a second vocabulary for the same fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from plaid import ApiClient, Configuration, Environment
from plaid.api import plaid_api
from plaid.model.accounts_get_request import AccountsGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from ..config import settings

_ENVIRONMENTS = {
    "sandbox": Environment.Sandbox,
    "production": Environment.Production,
}


class PlaidNotConfigured(RuntimeError):
    """No Plaid credentials in the environment, so no client can be built.

    A configuration fault rather than an HTTP one — the router turns it into a
    400, and the nightly job logs it.
    """


@dataclass(frozen=True)
class LinkedItem:
    """The result of exchanging a public token: the Item, and the token that
    from here on speaks for it."""

    item_id: str
    access_token: str


@dataclass(frozen=True)
class SyncPage:
    """One page of `/transactions/sync`.

    `has_more` means Plaid is still holding transactions past `next_cursor`;
    the caller pages until it is false and then stores the cursor it ended on.
    """

    added: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    next_cursor: str = ""
    has_more: bool = False


class PlaidClient(Protocol):
    """What the sync and the link flow need from Plaid. Implemented for real by
    `PlaidApiClient` and for tests by `tests.stub_plaid.StubPlaidClient`."""

    def create_link_token(self) -> str:
        """A short-lived token for Plaid Link to open with."""
        ...

    def exchange_public_token(self, public_token: str) -> LinkedItem:
        """Trade the one-shot public token from Link for a durable access token."""
        ...

    def accounts(self, access_token: str) -> list[dict[str, Any]]:
        """Every account on this Item, with balances, as Plaid returned them."""
        ...

    def sync_transactions(self, access_token: str, cursor: str) -> SyncPage:
        """The transactions added and removed since `cursor` (empty for a first sync)."""
        ...


class PlaidApiClient:
    """`PlaidClient` backed by the real `plaid-python` SDK."""

    def __init__(self, api: plaid_api.PlaidApi) -> None:
        self._api = api

    def create_link_token(self) -> str:
        resp = self._api.link_token_create(
            LinkTokenCreateRequest(
                user=LinkTokenCreateRequestUser(client_user_id="budget-app-local"),
                client_name="Earmark",
                products=[Products("transactions")],
                country_codes=[CountryCode("US")],
                language="en",
            )
        )
        return resp["link_token"]

    def exchange_public_token(self, public_token: str) -> LinkedItem:
        resp = self._api.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return LinkedItem(item_id=resp["item_id"], access_token=resp["access_token"])

    def accounts(self, access_token: str) -> list[dict[str, Any]]:
        resp = self._api.accounts_get(AccountsGetRequest(access_token=access_token))
        return [_as_dict(a) for a in resp["accounts"]]

    def sync_transactions(self, access_token: str, cursor: str) -> SyncPage:
        resp = self._api.transactions_sync(
            TransactionsSyncRequest(access_token=access_token, cursor=cursor)
        )
        return SyncPage(
            added=[_as_dict(t) for t in resp["added"]],
            removed=[_as_dict(r) for r in resp.get("removed", [])],
            next_cursor=resp["next_cursor"],
            has_more=resp["has_more"],
        )


def build_plaid_client() -> PlaidClient:
    """The configured client, or `PlaidNotConfigured` if there are no credentials."""
    if not settings.plaid_client_id or not settings.plaid_secret:
        raise PlaidNotConfigured("Plaid credentials not configured")
    cfg = Configuration(
        host=_ENVIRONMENTS.get(settings.plaid_env, Environment.Sandbox),
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return PlaidApiClient(plaid_api.PlaidApi(ApiClient(cfg)))


def _as_dict(obj: Any) -> dict[str, Any]:
    """SDK models index like dicts but are not dicts; the sync wants the real
    thing so it can store one verbatim and walk another without special cases."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)
