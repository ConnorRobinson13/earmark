"""The Plaid routes, and the promise that the nightly job does the same thing.

The sync used to live in the router, so the scheduler imported it back out of
the HTTP layer. Now both call `services.plaid_sync.run_sync`, and the parity
test below is what holds them together: the same stub, replayed through each
entry point, has to leave the database in exactly the same state.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app import db as db_module
from app import main
from app.config import settings
from app.models import Account, PlaidInbox, PlaidItem
from app.routers import plaid as plaid_router
from app.services import plaid_sync
from app.services.plaid_client import LinkedItem, PlaidNotConfigured, SyncPage
from stub_plaid import StubPlaidClient, plaid_account, plaid_transaction

CHECKING = "plaid-acct-checking"
TXN_DATE = date(2026, 6, 12)


@pytest.fixture(autouse=True)
def _fixed_floor(monkeypatch):
    monkeypatch.setattr(settings, "plaid_sync_floor_date", "2026-06-01")


@pytest.fixture()
def plaid(client):
    """A stub adapter, injected into the app the way the real client is."""
    stub = StubPlaidClient(
        accounts=[plaid_account(CHECKING, name="Everyday", available=500.0)],
        pages={
            "": SyncPage(
                added=[
                    plaid_transaction("txn-1", txn_date=TXN_DATE, account_id=CHECKING),
                    plaid_transaction(
                        "txn-2",
                        txn_date=TXN_DATE,
                        account_id=CHECKING,
                        amount=42.5,
                        merchant_name="Coffee",
                    ),
                ],
                next_cursor="cursor-1",
            )
        },
    )
    main.app.dependency_overrides[plaid_router.get_plaid_client] = lambda: stub
    try:
        yield stub
    finally:
        main.app.dependency_overrides.pop(plaid_router.get_plaid_client, None)


def seed_item() -> None:
    db = db_module.new_session()
    try:
        db.add(
            PlaidItem(
                item_id="item-stub",
                access_token="access-stub",
                institution_name="Stub Bank",
            )
        )
        db.commit()
    finally:
        db.close()


def snapshot() -> dict[str, object]:
    """Everything a sync is responsible for, in a comparable shape."""
    db = db_module.new_session()
    try:
        return {
            "inbox": [
                (r.plaid_transaction_id, r.merchant, str(r.amount), r.date, r.raw)
                for r in db.scalars(
                    select(PlaidInbox).order_by(PlaidInbox.plaid_transaction_id)
                ).all()
            ],
            "accounts": [
                (a.plaid_account_id, a.name, a.type, str(a.current_balance))
                for a in db.scalars(select(Account).order_by(Account.plaid_account_id)).all()
            ],
            "cursors": [
                (i.item_id, i.cursor)
                for i in db.scalars(select(PlaidItem).order_by(PlaidItem.item_id)).all()
            ],
        }
    finally:
        db.close()


def rewind() -> None:
    """Undo a sync's visible effects so the same pages can be replayed."""
    db = db_module.new_session()
    try:
        for row in db.scalars(select(PlaidInbox)).all():
            db.delete(row)
        for item in db.scalars(select(PlaidItem)).all():
            item.cursor = None
        db.commit()
    finally:
        db.close()


def test_manual_sync_and_the_scheduled_job_produce_identical_results(client, plaid):
    seed_item()

    scheduled_added = plaid_sync.run_daily_sync(plaid)
    after_job = snapshot()
    assert scheduled_added == 2

    rewind()

    resp = client.post("/plaid/sync")
    assert resp.status_code == 200
    assert resp.json() == {"added": scheduled_added}
    assert snapshot() == after_job


def test_the_scheduled_job_goes_through_the_service(monkeypatch):
    """The scheduler must not reach into a router to find the sync."""
    called: list[bool] = []
    monkeypatch.setattr(
        plaid_sync, "run_daily_sync", lambda *a, **kw: called.append(True) or 0
    )

    main._daily_sync_job()

    assert called == [True]


def test_sync_without_a_linked_item_is_a_400(client, plaid):
    assert client.post("/plaid/sync").status_code == 400


def test_link_token_comes_from_the_injected_client(client, plaid):
    resp = client.post("/plaid/link-token")

    assert resp.json() == {"link_token": "link-sandbox-stub"}
    assert ("create_link_token", None) in plaid.calls


def test_exchange_stores_the_item_and_its_accounts(client, plaid):
    plaid.linked_item = LinkedItem(item_id="item-exchanged", access_token="access-1")

    resp = client.post(
        "/plaid/exchange",
        json={"public_token": "public-1", "institution_name": "Stub Bank"},
    )

    assert resp.json() == {"item_id": "item-exchanged", "accounts_created": 1}
    listed = client.get("/plaid/items").json()
    assert [i["item_id"] for i in listed] == ["item-exchanged"]
    assert [a["name"] for a in listed[0]["accounts"]] == ["Everyday"]


def test_exchange_persists_nothing_when_the_accounts_fetch_fails(client, plaid):
    plaid.accounts_error = RuntimeError("Plaid is down")

    with pytest.raises(RuntimeError):
        client.post("/plaid/exchange", json={"public_token": "public-1"})

    assert client.get("/plaid/items").json() == []


def test_missing_credentials_are_reported_as_a_400(client, monkeypatch):
    """The dependency, not a handler, is what discovers there is no client."""
    monkeypatch.setattr(
        plaid_router, "build_plaid_client", _raise_not_configured
    )

    assert client.post("/plaid/link-token").status_code == 400


def _raise_not_configured():
    raise PlaidNotConfigured("Plaid credentials not configured")
