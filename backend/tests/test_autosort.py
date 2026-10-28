"""AI-assisted inbox auto-sorting.

These pin the three things that make the feature safe to ship:

* it is gated on OPENROUTER_API_KEY — no key means no outbound call and a 503,
  never a half-working endpoint;
* the model's output is never trusted: a hallucinated inbox row, an invalid or
  archived fund, or malformed JSON is dropped rather than approved;
* nothing is approved until the caller confirms — asking for suggestions changes
  no row, and a confirmation that names a bad fund aborts the whole batch.

The provider is mocked throughout (`FakeOpenRouter` stands in for
`httpx.post`), so the suite makes no live API call and needs no real key.
"""

from __future__ import annotations

import json
from datetime import UTC, date
from decimal import Decimal

import pytest
from app.models import Fund, FundKind, InboxStatus, PlaidInbox, Transaction


class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


class FakeOpenRouter:
    """Stands in for `httpx.post` inside the auto-sort service.

    `content` is what the model "replies"; tests set it after seeding so it can
    reference the real inbox ids. Every call is recorded so a test can assert the
    request the service built — the pinned model id and the key sent as a bearer
    token — and so a gating test can assert nothing went out at all.
    """

    def __init__(self) -> None:
        self.content = "[]"
        self.calls: list[dict] = []

    def __call__(self, url: str, *, headers=None, json=None, timeout=None):
        assert "openrouter.ai" in url, f"unexpected outbound request to {url}"
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return _FakeResponse(self.content)


@pytest.fixture()
def openrouter(monkeypatch) -> FakeOpenRouter:
    """Mock the HTTP client and hand the feature a key, so the provider is never
    actually reached. Tests that exercise the no-key path override the key."""
    from app.services import autosort

    fake = FakeOpenRouter()
    monkeypatch.setattr(autosort.httpx, "post", fake)
    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(autosort.settings, "openrouter_model", "typesafe/jev-router")
    return fake


def _inbox(s, *, plaid_id, merchant, amount, day, status=InboxStatus.pending):
    item = PlaidInbox(
        plaid_transaction_id=plaid_id,
        raw={"transaction_id": plaid_id},
        merchant=merchant,
        amount=Decimal(amount),
        date=day,
        status=status,
    )
    s.add(item)
    s.flush()
    return item


def _seed(*, archived: bool = False):
    """Two active funds (+ optionally an archived one) and a mix of inbox rows:
    two pending purchases, one pending income (Plaid signs income negative), and
    one purchase already approved. Returns the ids the tests need."""
    from app.db import new_session

    with new_session() as s:
        groceries = Fund(name="Groceries", kind=FundKind.operational)
        fuel = Fund(name="Fuel", kind=FundKind.operational)
        s.add_all([groceries, fuel])
        funds = {"groceries": groceries, "fuel": fuel}
        if archived:
            from datetime import datetime

            old = Fund(name="Old", kind=FundKind.operational)
            old.archived_at = datetime.now(UTC)
            s.add(old)
            funds["old"] = old
        s.flush()

        pending_a = _inbox(
            s,
            plaid_id="plaid-a",
            merchant="Trader Joe's",
            amount="42.00",
            day=date(2026, 3, 1),
        )
        pending_b = _inbox(
            s,
            plaid_id="plaid-b",
            merchant="Shell",
            amount="30.00",
            day=date(2026, 3, 2),
        )
        income = _inbox(
            s,
            plaid_id="plaid-i",
            merchant="Paycheck",
            amount="-1000.00",
            day=date(2026, 3, 4),
        )
        approved = _inbox(
            s,
            plaid_id="plaid-c",
            merchant="Costco",
            amount="10.00",
            day=date(2026, 3, 3),
            status=InboxStatus.approved,
        )
        s.flush()
        ids = {
            "groceries": groceries.id,
            "fuel": fuel.id,
            "old": funds["old"].id if archived else None,
            "item_a": pending_a.id,
            "item_b": pending_b.id,
            "income": income.id,
            "approved": approved.id,
        }
        s.commit()
    return ids


def _status_of(inbox_id: int):
    from app.db import new_session

    with new_session() as s:
        return s.get(PlaidInbox, inbox_id).status


def _ledger_size() -> int:
    from app.db import new_session
    from sqlalchemy import func, select

    with new_session() as s:
        return s.scalar(select(func.count()).select_from(Transaction))


# --------------------------------------------------------------------------
# Gating: no key
# --------------------------------------------------------------------------


def test_status_reports_disabled_without_a_key(client, monkeypatch):
    from app.services import autosort

    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    body = client.get("/autosort/status").json()
    assert body["enabled"] is False
    assert body["model"] == "typesafe/jev-router"


def test_suggestions_is_gated_off_without_a_key(client, monkeypatch):
    """No key: a clean 503 and — the point — no outbound request is attempted."""
    from app.services import autosort

    fake = FakeOpenRouter()
    monkeypatch.setattr(autosort.httpx, "post", fake)
    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    _seed()

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 503
    assert fake.calls == [], "called the provider with no key configured"


def test_confirm_is_gated_off_without_a_key(client, monkeypatch):
    from app.services import autosort

    monkeypatch.setattr(autosort.settings, "openrouter_api_key", "")
    ids = _seed()

    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["item_a"], "fund_id": ids["groceries"]}]},
    )
    assert resp.status_code == 503
    assert _status_of(ids["item_a"]) == InboxStatus.pending, (
        "approved with the feature gated off"
    )


# --------------------------------------------------------------------------
# Suggestions: read-only, validated, pinned model
# --------------------------------------------------------------------------


def test_suggestions_use_the_pinned_model_and_a_server_side_key(client, openrouter):
    ids = _seed()
    openrouter.content = json.dumps(
        [{"inbox_id": ids["item_a"], "fund_id": ids["groceries"]}]
    )

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 200, resp.text

    assert len(openrouter.calls) == 1
    call = openrouter.calls[0]
    assert call["json"]["model"] == "typesafe/jev-router"
    assert call["headers"].get("Authorization") == "Bearer test-key"


def test_suggestions_do_not_approve_anything(client, openrouter):
    """The read-only half: a suggestion proposes, it never writes."""
    ids = _seed()
    openrouter.content = json.dumps(
        [
            {"inbox_id": ids["item_a"], "fund_id": ids["fuel"]},
            {"inbox_id": ids["item_b"], "fund_id": ids["groceries"]},
        ]
    )

    resp = client.post("/autosort/suggestions")
    assert resp.status_code == 200, resp.text
    body = resp.json()["suggestions"]
    assert {s["inbox_id"] for s in body} == {ids["item_a"], ids["item_b"]}

    # Nothing moved: both are still pending and the ledger is untouched.
    assert _status_of(ids["item_a"]) == InboxStatus.pending
    assert _status_of(ids["item_b"]) == InboxStatus.pending
    assert _ledger_size() == 0


def test_suggestions_only_cover_pending_purchases(client, openrouter):
    """Approved rows and income are left out of the ask."""
    ids = _seed()
    # The model is never even offered these; if it names them anyway they drop.
    openrouter.content = json.dumps(
        [
            {"inbox_id": ids["approved"], "fund_id": ids["fuel"]},
            {"inbox_id": ids["income"], "fund_id": ids["fuel"]},
            {"inbox_id": ids["item_a"], "fund_id": ids["groceries"]},
        ]
    )

    body = client.post("/autosort/suggestions").json()["suggestions"]
    assert {s["inbox_id"] for s in body} == {ids["item_a"], ids["item_b"]}

    prompt = openrouter.calls[0]["json"]["messages"][0]["content"]
    assert "Trader Joe's" in prompt and "Shell" in prompt
    assert "Costco" not in prompt and "Paycheck" not in prompt


def test_invalid_model_output_is_dropped_not_approved(client, openrouter):
    """A hallucinated inbox row, an unknown fund and an archived fund are all
    discarded; only the one valid pairing survives."""
    ids = _seed(archived=True)
    openrouter.content = json.dumps(
        [
            {"inbox_id": 999999, "fund_id": ids["groceries"]},  # no such row
            {"inbox_id": ids["item_a"], "fund_id": 888888},  # no such fund
            {"inbox_id": ids["item_b"], "fund_id": ids["old"]},  # archived fund
            {"inbox_id": ids["item_a"], "fund_id": ids["fuel"]},  # the one good one
        ]
    )

    body = client.post("/autosort/suggestions").json()["suggestions"]
    assert body == [
        {
            "inbox_id": ids["item_a"],
            "merchant": "Trader Joe's",
            "amount": "42.00",
            "date": "2026-03-01",
            "suggested_fund_id": ids["fuel"],
            "suggested_fund_name": "Fuel",
        },
        # Shell's only proposal was invalid, so it is listed with no fund for the
        # reviewer to choose, rather than being dropped or guessed at.
        {
            "inbox_id": ids["item_b"],
            "merchant": "Shell",
            "amount": "30.00",
            "date": "2026-03-02",
            "suggested_fund_id": None,
            "suggested_fund_name": None,
        },
    ]


def test_malformed_model_output_leaves_every_row_without_a_fund(client, openrouter):
    """Not JSON yields the offered rows with no fund, not a crash or a guess."""
    ids = _seed()
    openrouter.content = "the model forgot to answer in JSON"
    body = client.post("/autosort/suggestions").json()["suggestions"]
    assert {s["inbox_id"] for s in body} == {ids["item_a"], ids["item_b"]}
    assert all(s["suggested_fund_id"] is None for s in body)


def test_declined_rows_are_listed_without_a_fund(client, openrouter):
    """The model saying null is a decline, not an error: the row still shows up
    so it can be assigned by hand."""
    ids = _seed()
    openrouter.content = json.dumps(
        [
            {"inbox_id": ids["item_a"], "fund_id": None},
            {"inbox_id": ids["item_b"], "fund_id": ids["fuel"]},
        ]
    )
    body = client.post("/autosort/suggestions").json()["suggestions"]
    by_id = {s["inbox_id"]: s for s in body}
    assert by_id[ids["item_a"]]["suggested_fund_id"] is None
    assert by_id[ids["item_b"]]["suggested_fund_id"] == ids["fuel"]


def test_a_row_with_no_fund_can_be_confirmed_once_a_fund_is_chosen(client, openrouter):
    """Confirm still requires a fund, so a hand-picked fund goes through the same
    validation as a suggested one."""
    ids = _seed()
    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["item_b"], "fund_id": ids["fuel"]}]},
    )
    assert resp.status_code == 200, resp.text
    assert _status_of(ids["item_b"]) == InboxStatus.approved


# --------------------------------------------------------------------------
# Confirm: the only writer, validated, atomic
# --------------------------------------------------------------------------


def test_confirm_approves_only_the_listed_row_and_preserves_the_rest(
    client, openrouter
):
    ids = _seed()

    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["item_a"], "fund_id": ids["groceries"]}]},
    )
    assert resp.status_code == 200, resp.text

    (updated,) = resp.json()["updated"]
    assert updated["fund_id"] == ids["groceries"]
    # Posted exactly as the inbox row says: an outflow, same date and merchant.
    assert updated["amount"] == "-42.00"
    assert updated["date"] == "2026-03-01"
    assert updated["merchant"] == "Trader Joe's"
    assert updated["plaid_transaction_id"] == "plaid-a"

    assert _status_of(ids["item_a"]) == InboxStatus.approved
    # The unconfirmed row is untouched.
    assert _status_of(ids["item_b"]) == InboxStatus.pending


def test_confirm_rejects_an_invalid_destination_without_mutating(client, openrouter):
    """A bad fund in the batch aborts the whole batch — no partial write."""
    ids = _seed(archived=True)

    resp = client.post(
        "/autosort/confirm",
        json={
            "changes": [
                {"inbox_id": ids["item_a"], "fund_id": ids["groceries"]},  # valid
                {"inbox_id": ids["item_b"], "fund_id": ids["old"]},  # archived
            ]
        },
    )
    assert resp.status_code == 400

    # Neither was approved, including the otherwise-valid first change.
    assert _status_of(ids["item_a"]) == InboxStatus.pending
    assert _status_of(ids["item_b"]) == InboxStatus.pending
    assert _ledger_size() == 0


def test_confirm_rejects_an_unknown_fund_without_mutating(client, openrouter):
    ids = _seed()
    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["item_a"], "fund_id": 777777}]},
    )
    assert resp.status_code == 400
    assert _status_of(ids["item_a"]) == InboxStatus.pending


def test_confirm_rejects_a_row_that_is_not_pending(client, openrouter):
    ids = _seed()
    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["approved"], "fund_id": ids["fuel"]}]},
    )
    assert resp.status_code == 400
    assert _ledger_size() == 0


def test_confirm_rejects_income(client, openrouter):
    """Paychecks are not sorted into funds; they land in Unassigned."""
    ids = _seed()
    resp = client.post(
        "/autosort/confirm",
        json={"changes": [{"inbox_id": ids["income"], "fund_id": ids["fuel"]}]},
    )
    assert resp.status_code == 400
    assert _status_of(ids["income"]) == InboxStatus.pending
