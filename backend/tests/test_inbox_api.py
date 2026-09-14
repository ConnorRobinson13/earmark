"""Approving an inbox item — the step that puts a Plaid transaction in the ledger.

The interesting case is the second approve of the *same* Plaid transaction.
`transactions.plaid_transaction_id` is unique, so a Plaid id the ledger already
holds cannot be posted again; production hit exactly that and answered the user
with a 500. These tests pin the rule the handler owns instead: approving an
inbox item leaves one ledger row for its Plaid id, tagged to the chosen fund.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app import db as db_module
from app.models import InboxStatus, PlaidInbox

TXN_DATE = date(2026, 8, 25)


@pytest.fixture()
def db(clean_db):
    session = db_module.new_session()
    try:
        yield session
    finally:
        session.close()


def stage_inbox_item(
    db,
    *,
    plaid_transaction_id: str = "plaid-txn-1",
    merchant: str = "Chick-fil-A",
    amount: str = "11.75",
    txn_date: date = TXN_DATE,
) -> int:
    """An inbox row as the sync writes it. Plaid signs purchases positive."""
    item = PlaidInbox(
        plaid_transaction_id=plaid_transaction_id,
        raw={"transaction_id": plaid_transaction_id},
        merchant=merchant,
        amount=Decimal(amount),
        date=txn_date,
    )
    db.add(item)
    db.commit()
    return item.id


def drop_inbox_row(db, inbox_id: int) -> None:
    """What the sync's `removed` reconciliation does to an inbox row — including
    one already approved, whose ledger transaction it leaves behind."""
    db.delete(db.get(PlaidInbox, inbox_id))
    db.commit()


def a_fund(client, name: str) -> int:
    return client.post("/funds", json={"name": name}).json()["id"]


def test_approving_posts_the_expense_to_the_chosen_fund(client, db):
    fund_id = a_fund(client, "Dining")
    inbox_id = stage_inbox_item(db)

    res = client.post(f"/inbox/{inbox_id}/approve", json={"fund_id": fund_id})

    assert res.status_code == 200
    posted = res.json()
    assert posted["fund_id"] == fund_id
    assert Decimal(posted["amount"]) == Decimal("-11.75")
    assert posted["plaid_transaction_id"] == "plaid-txn-1"
    assert client.get("/inbox").json() == []


def test_approving_a_plaid_transaction_the_ledger_already_holds_adopts_it(client, db):
    """The sync can re-stage a Plaid id that was approved once already: a
    `removed` page deletes the inbox row, and a later page re-adds it with
    nothing left in the inbox to dedupe against. Approving that row must not
    try to post the Plaid id a second time — the unique constraint on
    `transactions.plaid_transaction_id` made that a 500."""
    dining = a_fund(client, "Dining")
    approved = stage_inbox_item(db)
    first = client.post(f"/inbox/{approved}/approve", json={"fund_id": dining}).json()
    drop_inbox_row(db, approved)

    restaged = stage_inbox_item(db)  # same plaid id, fresh row — the zombie

    res = client.post(f"/inbox/{restaged}/approve", json={"fund_id": dining})

    assert res.status_code == 200
    assert res.json()["id"] == first["id"]
    ledger = client.get("/transactions").json()
    assert [t["id"] for t in ledger] == [first["id"]]
    assert client.get("/inbox").json() == []


def test_adopting_retags_the_posted_transaction_to_the_fund_just_chosen(client, db):
    dining = a_fund(client, "Dining")
    groceries = a_fund(client, "Groceries")
    approved = stage_inbox_item(db)
    first = client.post(f"/inbox/{approved}/approve", json={"fund_id": dining}).json()
    drop_inbox_row(db, approved)

    res = client.post(
        f"/inbox/{stage_inbox_item(db)}/approve", json={"fund_id": groceries}
    )

    assert res.status_code == 200
    assert res.json()["id"] == first["id"]
    assert res.json()["fund_id"] == groceries
    assert [t["id"] for t in client.get("/transactions").json()] == [first["id"]]


def test_the_adopted_item_is_marked_reviewed(client, db):
    dining = a_fund(client, "Dining")
    approved = stage_inbox_item(db)
    client.post(f"/inbox/{approved}/approve", json={"fund_id": dining})
    drop_inbox_row(db, approved)
    restaged = stage_inbox_item(db)

    client.post(f"/inbox/{restaged}/approve", json={"fund_id": dining})

    db.expire_all()
    row = db.get(PlaidInbox, restaged)
    assert row.status == InboxStatus.approved
    assert row.reviewed_at is not None


def test_approving_an_item_that_is_not_pending_is_a_404(client, db):
    fund_id = a_fund(client, "Dining")
    inbox_id = stage_inbox_item(db)
    client.post(f"/inbox/{inbox_id}/approve", json={"fund_id": fund_id})

    assert client.post(
        f"/inbox/{inbox_id}/approve", json={"fund_id": fund_id}
    ).status_code == 404


def test_losing_a_race_to_post_the_plaid_id_adopts_instead_of_500ing(client, db, monkeypatch):
    """The ledger lookup is a read: another approve of the same Plaid id can post
    between it and the insert, and the unique index rejects the loser. Blinding
    the first lookup reproduces that stale read — the request has to roll back
    and adopt the winner's row rather than hand the user a 500."""
    from app.routers import inbox as inbox_router

    dining = a_fund(client, "Dining")
    groceries = a_fund(client, "Groceries")
    approved = stage_inbox_item(db)
    first = client.post(f"/inbox/{approved}/approve", json={"fund_id": dining}).json()
    drop_inbox_row(db, approved)
    restaged = stage_inbox_item(db)

    real_find = inbox_router.tx_svc.find_by_plaid_id
    seen: list[str] = []

    def blind_on_first_look(session, plaid_transaction_id):
        seen.append(plaid_transaction_id)
        if len(seen) == 1:
            return None  # as if the winner had not committed yet
        return real_find(session, plaid_transaction_id)

    monkeypatch.setattr(inbox_router.tx_svc, "find_by_plaid_id", blind_on_first_look)

    res = client.post(f"/inbox/{restaged}/approve", json={"fund_id": groceries})

    assert res.status_code == 200
    assert res.json()["id"] == first["id"]
    assert res.json()["fund_id"] == groceries
    assert [t["id"] for t in client.get("/transactions").json()] == [first["id"]]
    db.expire_all()
    assert db.get(PlaidInbox, restaged).status == InboxStatus.approved


def test_approving_adopts_a_row_the_importer_posted_outside_the_inbox(client, db):
    """Production's shape: the ledger already holds the Plaid id, but nothing in
    the inbox was ever approved from it — the row came from the bulk importer
    (or a sync that posted directly), so there is no earlier approve to have
    marked anything reviewed. The pending row still has to adopt that entry and
    retag it, not post the Plaid id a second time.
    """
    from app.services import transactions as tx_svc

    dining = a_fund(client, "Dining")
    groceries = a_fund(client, "Groceries")
    existing = tx_svc.post_expense(
        db,
        fund_id=dining,
        amount=Decimal("11.75"),
        txn_date=TXN_DATE,
        merchant="Chick-fil-A",
        plaid_transaction_id="plaid-txn-1",
    )
    db.commit()
    existing_id = existing.id

    inbox_id = stage_inbox_item(db)  # same Plaid id, never approved from

    res = client.post(f"/inbox/{inbox_id}/approve", json={"fund_id": groceries})

    assert res.status_code == 200
    assert res.json()["id"] == existing_id
    assert res.json()["fund_id"] == groceries
    assert Decimal(res.json()["amount"]) == Decimal("-11.75")
    assert [t["id"] for t in client.get("/transactions").json()] == [existing_id]
    assert client.get("/inbox").json() == []
