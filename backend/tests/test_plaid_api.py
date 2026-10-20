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
from app.services.plaid_client import LinkedItem, PlaidApiError, PlaidNotConfigured, SyncPage
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
    plaid_router.clear_item_status_cache()
    main.app.dependency_overrides[plaid_router.get_plaid_client] = lambda: stub
    main.app.dependency_overrides[plaid_router.get_optional_plaid_client] = lambda: stub
    try:
        yield stub
    finally:
        main.app.dependency_overrides.pop(plaid_router.get_plaid_client, None)
        main.app.dependency_overrides.pop(plaid_router.get_optional_plaid_client, None)
        plaid_router.clear_item_status_cache()


def seed_item(
    *,
    item_id: str = "item-stub",
    access_token: str = "access-stub",
    institution_name: str = "Stub Bank",
) -> int:
    db = db_module.new_session()
    try:
        item = PlaidItem(
            item_id=item_id,
            access_token=access_token,
            institution_name=institution_name,
        )
        db.add(item)
        db.flush()
        item_pk = item.id
        db.commit()
        return item_pk
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
    assert resp.json() == {"added": scheduled_added, "issues": []}
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


def test_manual_sync_identifies_login_required_item_and_continues_other_items(
    client, plaid, monkeypatch
):
    needs_login_id = seed_item(
        item_id="item-needs-login",
        access_token="access-needs-login",
        institution_name="Needs Login Bank",
    )
    db = db_module.new_session()
    try:
        db.add(
            PlaidItem(
                item_id="item-healthy",
                access_token="access-healthy",
                institution_name="Healthy Bank",
            )
        )
        db.commit()
    finally:
        db.close()

    original_accounts = plaid.accounts

    def accounts(access_token):
        if access_token == "access-needs-login":
            raise PlaidApiError(
                error_code="ITEM_LOGIN_REQUIRED",
                error_message="Login required",
                status=400,
            )
        return original_accounts(access_token)

    monkeypatch.setattr(plaid, "accounts", accounts)

    response = client.post("/plaid/sync")

    assert response.status_code == 200
    assert response.json() == {
        "added": 2,
        "issues": [
            {
                "id": needs_login_id,
                "institution_name": "Needs Login Bank",
                "error_code": "ITEM_LOGIN_REQUIRED",
                "needs_reauthentication": True,
            }
        ],
    }
    cursors = dict(snapshot()["cursors"])
    assert cursors == {"item-healthy": "cursor-1", "item-needs-login": None}


def test_link_token_comes_from_the_injected_client(client, plaid):
    resp = client.post("/plaid/link-token")

    assert resp.json() == {"link_token": "link-sandbox-stub"}
    assert ("create_link_token", None) in plaid.calls


def test_update_link_token_is_created_for_the_selected_item(client, plaid):
    item_pk = seed_item(access_token="existing-access-token")

    response = client.post(f"/plaid/items/{item_pk}/update-link-token")

    assert response.status_code == 200
    assert response.json() == {"link_token": "link-update-stub"}
    assert ("create_update_link_token", "existing-access-token") in plaid.calls


def test_update_link_token_rejects_a_missing_item(client, plaid):
    response = client.post("/plaid/items/999/update-link-token")

    assert response.status_code == 404


def test_update_link_token_provider_error_is_safe_502(client, plaid, monkeypatch):
    item_pk = seed_item()

    def fail_update(_access_token):
        raise PlaidApiError(
            error_code="ITEM_NOT_FOUND",
            error_message="Internal provider details",
            status=400,
        )

    monkeypatch.setattr(plaid, "create_update_link_token", fail_update)

    response = client.post(f"/plaid/items/{item_pk}/update-link-token")

    assert response.status_code == 502
    assert response.json() == {
        "detail": {
            "code": "PLAID_UPDATE_LINK_FAILED",
            "error_code": "ITEM_NOT_FOUND",
            "message": "Plaid no longer recognizes this linked Item; update mode cannot repair it.",
        }
    }
    assert "Internal provider details" not in response.text


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


def test_items_exposes_login_required_status_without_manual_sync(client, plaid):
    item_pk = seed_item(
        access_token="access-needs-login",
        institution_name="Needs login",
    )
    plaid.item_errors["access-needs-login"] = "ITEM_LOGIN_REQUIRED"

    response = client.get("/plaid/items")

    assert response.status_code == 200
    item = response.json()[0]
    assert item["id"] == item_pk
    assert item["error_code"] == "ITEM_LOGIN_REQUIRED"
    assert item["needs_reauthentication"] is True
    assert item["status_available"] is True
    assert ("item_error_code", "access-needs-login") in plaid.calls

    client.get("/plaid/items")
    assert plaid.calls.count(("item_error_code", "access-needs-login")) == 1


def test_items_does_not_turn_status_probe_failure_into_item_error(client, plaid):
    seed_item()
    plaid.item_errors["access-stub"] = PlaidApiError(
        error_code="RATE_LIMIT_EXCEEDED",
        error_message="Transient Plaid response",
        status=429,
    )

    item = client.get("/plaid/items").json()[0]

    assert item["error_code"] is None
    assert item["needs_reauthentication"] is False
    assert item["status_available"] is False


def test_items_surfaces_permanent_invalid_access_token_status(client, plaid):
    seed_item()
    plaid.item_errors["access-stub"] = PlaidApiError(
        error_code="INVALID_ACCESS_TOKEN",
        error_message="Invalid Item access token",
        status=400,
    )

    item = client.get("/plaid/items").json()[0]

    assert item["error_code"] == "INVALID_ACCESS_TOKEN"
    assert item["needs_reauthentication"] is False
    assert item["status_available"] is True


def test_missing_credentials_are_reported_as_a_400(client, monkeypatch):
    """The dependency, not a handler, is what discovers there is no client."""
    monkeypatch.setattr(
        plaid_router, "build_plaid_client", _raise_not_configured
    )

    response = client.post("/plaid/link-token")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "PLAID_CREDENTIALS_NOT_CONFIGURED"


def _raise_not_configured():
    raise PlaidNotConfigured("Plaid credentials not configured")
