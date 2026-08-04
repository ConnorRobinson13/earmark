"""The Plaid sync, driven end to end by a stub adapter.

Every rule the sync owns is exercised here against `StubPlaidClient`: the floor
date that keeps two years of backfill out of the inbox, the pending skip, the
deduplication that makes a re-run a no-op, investment suppression, the removed
reconciliation that clears zombie rows, and cursor advancement across pages.
None of it touches the Plaid SDK or a sandbox account — that is the whole point
of the port the sync now takes as an argument.

Dates are literals rather than offsets from today, so no expectation here can go
stale, and the floor is set per-test instead of inherited from settings.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app import db as db_module
from app.config import settings
from app.models import Account, AccountType, PlaidInbox, PlaidItem
from app.services import plaid_sync
from app.services.plaid_client import SyncPage
from stub_plaid import StubPlaidClient, plaid_account, plaid_transaction

FLOOR = date(2026, 6, 1)
BEFORE_FLOOR = date(2026, 5, 30)
AFTER_FLOOR = date(2026, 6, 12)

CHECKING = "plaid-acct-checking"
BROKERAGE = "plaid-acct-brokerage"


@pytest.fixture()
def db(clean_db):
    """A session on the throwaway database, owned by the test."""
    session = db_module.new_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _fixed_floor(monkeypatch):
    """Pin the floor so these tests describe it instead of inheriting it."""
    monkeypatch.setattr(settings, "plaid_sync_floor_date", FLOOR.isoformat())


def seeded_item(db, *, access_token: str = "access-stub") -> PlaidItem:
    item = PlaidItem(
        item_id="item-stub", access_token=access_token, institution_name="Stub Bank"
    )
    db.add(item)
    db.commit()
    return item


def one_page(*added, removed=(), next_cursor: str = "cursor-1") -> dict[str, SyncPage]:
    """A single page of results answering the opening (empty) cursor."""
    return {
        "": SyncPage(
            added=list(added),
            removed=list(removed),
            next_cursor=next_cursor,
            has_more=False,
        )
    }


def stub_with(pages, *, accounts=None) -> StubPlaidClient:
    return StubPlaidClient(
        pages=pages,
        accounts=accounts if accounts is not None else [plaid_account(CHECKING)],
    )


def inbox_ids(db) -> list[str]:
    db.expire_all()
    return list(
        db.scalars(
            select(PlaidInbox.plaid_transaction_id).order_by(
                PlaidInbox.plaid_transaction_id
            )
        ).all()
    )


# ---------- floor date ----------

def test_transactions_dated_before_the_floor_are_dropped(db):
    client = stub_with(
        one_page(
            plaid_transaction("old", txn_date=BEFORE_FLOOR, account_id=CHECKING),
            plaid_transaction("new", txn_date=AFTER_FLOOR, account_id=CHECKING),
        )
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1
    assert inbox_ids(db) == ["new"]


def test_a_transaction_on_the_floor_date_itself_is_kept(db):
    client = stub_with(
        one_page(plaid_transaction("on-the-day", txn_date=FLOOR, account_id=CHECKING))
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1
    assert inbox_ids(db) == ["on-the-day"]


def test_an_unparseable_floor_date_lets_everything_through(db, monkeypatch):
    """A typo in the setting must not silently swallow the whole backfill."""
    monkeypatch.setattr(settings, "plaid_sync_floor_date", "not-a-date")
    client = stub_with(
        one_page(plaid_transaction("ancient", txn_date=date(2019, 1, 1), account_id=CHECKING))
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1


# ---------- deduplication ----------

def test_an_already_seen_transaction_is_not_added_twice(db):
    """Plaid replays a transaction whenever the cursor is reset or a sync is
    retried; the second pass must add nothing."""
    client = stub_with(
        one_page(plaid_transaction("txn-1", txn_date=AFTER_FLOOR, account_id=CHECKING))
    )
    item = seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1

    # Rewind the cursor so Plaid hands us the same page again.
    db.expire_all()
    item = db.get(PlaidItem, item.id)
    item.cursor = None
    db.commit()

    assert plaid_sync.run_sync(db, client) == 0
    assert inbox_ids(db) == ["txn-1"]


def test_pending_transactions_are_skipped(db):
    """Pending rows carry pre-settlement amounts and a transaction_id that Plaid
    throws away once they post."""
    client = stub_with(
        one_page(
            plaid_transaction(
                "pending-1", txn_date=AFTER_FLOOR, account_id=CHECKING, pending=True
            ),
            plaid_transaction("posted-1", txn_date=AFTER_FLOOR, account_id=CHECKING),
        )
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1
    assert inbox_ids(db) == ["posted-1"]


def test_investment_transactions_are_suppressed(db):
    """Only the balance of an investment account is tracked — buys, sells and
    dividends would flood the inbox with rows nobody wants to categorise."""
    client = stub_with(
        one_page(
            plaid_transaction("buy-vti", txn_date=AFTER_FLOOR, account_id=BROKERAGE),
            plaid_transaction("groceries", txn_date=AFTER_FLOOR, account_id=CHECKING),
        ),
        accounts=[
            plaid_account(CHECKING),
            plaid_account(
                BROKERAGE, name="Brokerage", type_="investment", subtype="brokerage"
            ),
        ],
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1
    assert inbox_ids(db) == ["groceries"]


# ---------- removed reconciliation ----------

def test_a_removed_transaction_deletes_its_inbox_row(db):
    """Plaid emits `removed` for reversals and for the pending id that a posted
    transaction replaces. Either way the inbox row is a zombie."""
    client = stub_with(
        one_page(plaid_transaction("txn-1", txn_date=AFTER_FLOOR, account_id=CHECKING))
    )
    item = seeded_item(db)
    plaid_sync.run_sync(db, client)
    assert inbox_ids(db) == ["txn-1"]

    reversal = stub_with(
        {
            "cursor-1": SyncPage(
                removed=[{"transaction_id": "txn-1"}],
                next_cursor="cursor-2",
                has_more=False,
            )
        }
    )
    assert plaid_sync.run_sync(db, reversal) == 0
    assert inbox_ids(db) == []

    db.expire_all()
    assert db.get(PlaidItem, item.id).cursor == "cursor-2"


def test_a_removal_without_an_id_does_not_abandon_the_rest_of_the_page(db):
    """One malformed row must not raise past the commit and discard every
    transaction already staged for every item."""
    client = stub_with(
        {
            "": SyncPage(
                added=[plaid_transaction("txn-1", txn_date=AFTER_FLOOR, account_id=CHECKING)],
                removed=[{}],
                next_cursor="cursor-1",
            )
        }
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 1
    assert inbox_ids(db) == ["txn-1"]


def test_removing_an_unknown_transaction_is_harmless(db):
    client = stub_with(
        {"": SyncPage(removed=[{"transaction_id": "never-seen"}], next_cursor="c1")}
    )
    seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 0
    assert inbox_ids(db) == []


# ---------- cursor advancement ----------

def test_paging_follows_has_more_and_stores_the_final_cursor(db):
    client = stub_with(
        {
            "": SyncPage(
                added=[plaid_transaction("p1", txn_date=AFTER_FLOOR, account_id=CHECKING)],
                next_cursor="cursor-1",
                has_more=True,
            ),
            "cursor-1": SyncPage(
                added=[plaid_transaction("p2", txn_date=AFTER_FLOOR, account_id=CHECKING)],
                next_cursor="cursor-2",
                has_more=False,
            ),
        }
    )
    item = seeded_item(db)

    assert plaid_sync.run_sync(db, client) == 2
    assert inbox_ids(db) == ["p1", "p2"]
    db.expire_all()
    assert db.get(PlaidItem, item.id).cursor == "cursor-2"


def test_a_stored_cursor_is_where_the_next_sync_resumes(db):
    client = stub_with(
        {
            "cursor-1": SyncPage(
                added=[plaid_transaction("later", txn_date=AFTER_FLOOR, account_id=CHECKING)],
                next_cursor="cursor-2",
            )
        }
    )
    item = seeded_item(db)
    item.cursor = "cursor-1"
    db.commit()

    assert plaid_sync.run_sync(db, client) == 1
    assert ("sync_transactions", "cursor-1") in client.calls


def test_no_linked_items_means_no_plaid_calls(db):
    client = stub_with(one_page())

    assert plaid_sync.run_sync(db, client) == 0
    assert client.calls == []


# ---------- balances ----------

def test_syncing_refreshes_account_balances_before_ingesting(db):
    """Accounts are upserted first so an inbox row can be attributed to a row
    that exists — including on the very first sync of a new Item."""
    client = stub_with(
        one_page(plaid_transaction("txn-1", txn_date=AFTER_FLOOR, account_id=CHECKING)),
        accounts=[plaid_account(CHECKING, name="Everyday", available=812.45, current=900.0)],
    )
    seeded_item(db)

    plaid_sync.run_sync(db, client)

    db.expire_all()
    acct = db.scalar(select(Account).where(Account.plaid_account_id == CHECKING))
    assert acct is not None
    assert acct.name == "Everyday"
    # Checking prefers `available`: it nets out pending charges.
    assert str(acct.current_balance) == "812.45"
    assert acct.last_synced_at is not None

    row = db.scalar(select(PlaidInbox).where(PlaidInbox.plaid_transaction_id == "txn-1"))
    assert row.account_id == acct.id
    # The raw payload is stored JSON-safe — a `date` would break psycopg's encoder.
    assert row.raw["date"] == AFTER_FLOOR.isoformat()


def test_a_credit_card_stores_the_amount_owed(db):
    client = stub_with(
        one_page(),
        accounts=[
            plaid_account(
                "plaid-acct-card",
                name="Rewards Card",
                type_="credit",
                subtype="credit card",
                available=1500.0,
                current=243.10,
            )
        ],
    )
    seeded_item(db)

    plaid_sync.run_sync(db, client)

    db.expire_all()
    acct = db.scalar(select(Account).where(Account.plaid_account_id == "plaid-acct-card"))
    assert acct.type == AccountType.credit
    assert str(acct.current_balance) == "243.10"


# ---------- linking ----------

def test_linking_stores_the_item_and_its_accounts(db):
    client = StubPlaidClient(accounts=[plaid_account(CHECKING, name="Everyday")])

    result = plaid_sync.link_item(db, client, "public-token-1", "Stub Bank")

    assert result.item_id == "item-stub"
    assert result.accounts_created == 1
    db.expire_all()
    item = db.scalar(select(PlaidItem))
    assert item.access_token == "access-stub"
    assert item.institution_name == "Stub Bank"
    acct = db.scalar(select(Account).where(Account.plaid_account_id == CHECKING))
    assert acct.plaid_item_id == item.id


def test_a_failed_account_fetch_leaves_no_item_behind(db):
    """The exchange used to commit the Item and then fetch accounts, so a
    failure here stranded an Item with nothing under it — invisible in the UI
    and impossible to re-link, because Plaid had already burned the token."""
    client = StubPlaidClient(accounts_error=RuntimeError("Plaid is down"))

    with pytest.raises(RuntimeError):
        plaid_sync.link_item(db, client, "public-token-1", "Stub Bank")

    db.rollback()
    assert db.scalars(select(PlaidItem)).all() == []
    assert db.scalars(select(Account)).all() == []
