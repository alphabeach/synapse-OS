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


def test_restock_requires_lot_and_expiry(member):
    item = item_named(member, "DMEM/F12 Medium (500 mL)")
    response = member.post(f"/api/items/{item['id']}/restock", json={
        "quantity": 2, "lot_number": "X", "expiry_date": "not-a-date",
        "location": "BGC 4C Fridge",
    })
    assert response.status_code == 400


def test_search_escapes_like_wildcards(member):
    # '%' must match a literal percent sign, not every row.
    hits = member.get("/api/items", params={"q": "%"}).json()
    assert [h["name"] for h in hits] == ["Ethanol 70%"]
    # '_' is likewise literal, and no seeded name contains one.
    assert member.get("/api/items", params={"q": "_"}).json() == []
