"""Categories are a managed list that funds choose from, not free text.

The web UI offers a list and a create form, but the API is the only place a
second client (the MCP server) can meet the same rules, so these pin them there:
names are unique regardless of case, a fund can only point at a listed category,
and a category still in use cannot be deleted out from under its funds.
"""

from __future__ import annotations


def test_created_categories_are_listed_alphabetically(client):
    client.post("/categories", json={"name": "Housing"})
    client.post("/categories", json={"name": "food"})

    names = [c["name"] for c in client.get("/categories").json()]

    assert names == ["food", "Housing"]


def test_a_name_is_unique_regardless_of_case(client):
    client.post("/categories", json={"name": "Food"})

    resp = client.post("/categories", json={"name": "  FOOD  "})

    assert resp.status_code == 409
    assert len(client.get("/categories").json()) == 1


def test_a_blank_name_is_refused(client):
    assert client.post("/categories", json={"name": "   "}).status_code == 422


def test_a_fund_takes_a_listed_category_and_reports_its_name(client):
    food = client.post("/categories", json={"name": "Food"}).json()

    fund = client.post(
        "/funds",
        json={"name": "Groceries", "kind": "operational", "category_id": food["id"]},
    ).json()

    assert fund["category_id"] == food["id"]
    assert fund["category"] == "Food"


def test_an_unknown_category_id_is_refused_on_create_and_update(client):
    created = client.post("/funds", json={"name": "Rent", "kind": "operational"}).json()

    create = client.post(
        "/funds", json={"name": "Gas", "kind": "operational", "category_id": 9999}
    )
    update = client.patch(f"/funds/{created['id']}", json={"category_id": 9999})

    assert create.status_code == 422
    assert update.status_code == 422


def test_a_fund_can_be_moved_to_another_category_and_cleared(client):
    food = client.post("/categories", json={"name": "Food"}).json()
    home = client.post("/categories", json={"name": "Housing"}).json()
    fund = client.post(
        "/funds",
        json={"name": "Groceries", "kind": "operational", "category_id": food["id"]},
    ).json()

    moved = client.patch(
        f"/funds/{fund['id']}", json={"category_id": home["id"]}
    ).json()
    cleared = client.patch(f"/funds/{fund['id']}", json={"category_id": None}).json()

    assert moved["category"] == "Housing"
    assert cleared["category_id"] is None
    assert cleared["category"] is None


def test_a_category_in_use_cannot_be_deleted(client):
    food = client.post("/categories", json={"name": "Food"}).json()
    client.post(
        "/funds",
        json={"name": "Groceries", "kind": "operational", "category_id": food["id"]},
    )

    resp = client.delete(f"/categories/{food['id']}")

    assert resp.status_code == 409
    assert [c["name"] for c in client.get("/categories").json()] == ["Food"]


def test_an_unused_category_can_be_deleted(client):
    food = client.post("/categories", json={"name": "Food"}).json()

    assert client.delete(f"/categories/{food['id']}").status_code == 200
    assert client.get("/categories").json() == []
