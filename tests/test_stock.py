"""Stock safety: guarded concurrent consumption, FEFO, optimistic recount."""
from concurrent.futures import ThreadPoolExecutor

from tests.conftest import item_named


def test_concurrent_consumers_never_drive_stock_negative(member):
    # 40 racks on hand, 20 buyers want 3 each: exactly 13 can win.
    item = item_named(member, "Filtered Pipette Tips 200 uL")
    start = item["quantity_on_hand"]

    def buy(_):
        return member.post(
            f"/api/items/{item['id']}/consume", json={"quantity": 3}
        ).status_code

    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(pool.map(buy, range(20)))

    ok = codes.count(200)
    assert ok == start // 3, codes
    assert all(c in (200, 400) for c in codes), codes

    after = member.get(f"/api/items/{item['id']}").json()
    assert after["quantity_on_hand"] == start - ok * 3
    assert after["quantity_on_hand"] >= 0


def test_consume_beyond_stock_is_a_clean_400(member):
    item = item_named(member, "B-27 Supplement (50x)")
    response = member.post(
        f"/api/items/{item['id']}/consume",
        json={"quantity": item["quantity_on_hand"] + 1},
    )
    assert response.status_code == 400
    assert "insufficient" in response.json()["detail"]


def test_consume_drains_earliest_expiry_first(member, db):
    item = item_named(member, "B-27 Supplement (50x)")
    lots = sorted(
        db.execute(
            "SELECT id, expiry_date, quantity FROM lot WHERE item_id = ? ORDER BY expiry_date",
            (item["id"],),
        ).fetchall(),
        key=lambda r: r["expiry_date"],
    )
    assert lots[0]["quantity"] > 0
    member.post(f"/api/items/{item['id']}/consume", json={"quantity": 1})
    after = db.execute(
        "SELECT quantity FROM lot WHERE id = ?", (lots[0]["id"],)
    ).fetchone()["quantity"]
    assert after == lots[0]["quantity"] - 1


def test_recount_with_stale_expectation_conflicts(member, db):
    item = item_named(member, "Ethanol 70%")
    stale = item["quantity_on_hand"]
    # Someone else takes one unit between the client reading and submitting.
    db.execute("UPDATE item SET quantity_on_hand = quantity_on_hand - 1 WHERE id = ?",
               (item["id"],))
    db.commit()

    response = member.post(
        f"/api/items/{item['id']}/recount",
        json={"expected_quantity": stale, "quantity": stale},
    )
    assert response.status_code == 409
    assert "stock changed" in response.json()["detail"]

    # Retrying with the true value succeeds.
    current = member.get(f"/api/items/{item['id']}").json()["quantity_on_hand"]
    retry = member.post(
        f"/api/items/{item['id']}/recount",
        json={"expected_quantity": current, "quantity": 7, "reason": "physical count"},
    )
    assert retry.status_code == 200
    assert retry.json()["quantity_on_hand"] == 7


def test_recount_decrease_drains_lots_and_clears_expiry_alert(member, db):
    item = item_named(member, "B-27 Supplement (50x)")  # its lot expires in 18 days
    lots_before = db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM lot WHERE item_id = ?", (item["id"],)
    ).fetchone()[0]
    assert lots_before == item["quantity_on_hand"]

    response = member.post(
        f"/api/items/{item['id']}/recount",
        json={"expected_quantity": item["quantity_on_hand"], "quantity": 0,
              "reason": "expired and discarded"},
    )
    assert response.status_code == 200, response.text

    after = db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM lot WHERE item_id = ?", (item["id"],)
    ).fetchone()[0]
    assert after == 0
    expiring = member.get("/api/dashboard").json()["expiring"]
    assert all(a["item_id"] != item["id"] for a in expiring)


def test_recount_increase_creates_an_adjustment_lot(member, db):
    item = item_named(member, "Ethanol 70%")
    target = item["quantity_on_hand"] + 4

    response = member.post(
        f"/api/items/{item['id']}/recount",
        json={"expected_quantity": item["quantity_on_hand"], "quantity": target,
              "reason": "found unlabelled stock"},
    )
    assert response.status_code == 200, response.text

    total = db.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM lot WHERE item_id = ?", (item["id"],)
    ).fetchone()[0]
    assert total == target
    adjustment = db.execute(
        "SELECT lot_number, quantity FROM lot WHERE item_id = ? AND lot_number LIKE 'ADJ-%'",
        (item["id"],),
    ).fetchone()
    assert adjustment["quantity"] == 4


def test_restock_requires_lot_and_expiry(member):
    item = item_named(member, "DMEM/F12 Medium (500 mL)")
    response = member.post(f"/api/items/{item['id']}/restock", json={
        "quantity": 2, "lot_number": "X", "expiry_date": "not-a-date",
        "location": "BGC 4C Fridge",
    })
    assert response.status_code == 400


def test_out_of_range_item_numbers_are_400(admin):
    for bad in (
        {"daily_burn_rate": -0.1}, {"safety_stock": -1},
        {"lead_time_days": -1}, {"unit_cost_php": -1},
    ):
        response = admin.post("/api/items", json={"name": "Bad Input", **bad})
        assert response.status_code == 400, (bad, response.text)


def test_search_escapes_like_wildcards(member):
    # '%' must match a literal percent sign, not every row.
    hits = member.get("/api/items", params={"q": "%"}).json()
    assert [h["name"] for h in hits] == ["Ethanol 70%"]
    # '_' is likewise literal, and no seeded name contains one.
    assert member.get("/api/items", params={"q": "_"}).json() == []


def test_item_payload_exposes_storage_location_and_reorder_level(viewer):
    items = viewer.get("/api/items").json()
    assert items
    assert all("storage_location" in i and "reorder_level" in i for i in items)
    item = next(i for i in items if i["storage_location"])
    detail = viewer.get(f"/api/items/{item['id']}").json()
    active = [lot["location"] for lot in detail["lots"] if lot["quantity"] > 0]
    assert detail["storage_location"] in active
