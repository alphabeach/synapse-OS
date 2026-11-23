"""Quote matrix and the atomic award -> PO conversion."""
from tests.conftest import item_named


def _quotes(client, item):
    return client.get("/api/quotes", params={"item_id": item["id"]}).json()


def test_matrix_is_php_landed_cost_sorted(member):
    item = item_named(member, "Phospho-Tau (pS396) Antibody")
    quotes = _quotes(member, item)
    assert len(quotes) == 3
    for q in quotes:
        assert q["landed_cost_php"] > 0
        assert q["effective_lead_days"] == q["lead_time_days"] + q["boc_buffer_days"]
    assert quotes == sorted(quotes, key=lambda q: q["landed_cost_php"])


def test_award_marks_primary_and_backup_and_creates_po(member, db):
    item = item_named(member, "DMEM/F12 Medium (500 mL)")
    target = next(q for q in _quotes(member, item) if q["supplier_type"] == "alibaba")

    response = member.post(f"/api/quotes/{target['id']}/award", json={})
    assert response.status_code == 200, response.text
    body = response.json()

    po = db.execute(
        "SELECT * FROM purchase_order WHERE id = ?", (body["po_id"],)
    ).fetchone()
    assert po["quantity"] == target["moq"]
    assert po["is_import"] == 1
    assert po["status"] == "po_placed"

    primaries = db.execute(
        "SELECT id FROM quote WHERE item_id = ? AND status = 'primary'", (item["id"],)
    ).fetchall()
    assert [r["id"] for r in primaries] == [target["id"]]

    backups = db.execute(
        "SELECT id FROM quote WHERE item_id = ? AND status = 'backup'", (item["id"],)
    ).fetchall()
    assert [r["id"] for r in backups] == [body["backup_quote_id"]]

    # The same quote cannot be awarded twice.
    again = member.post(f"/api/quotes/{target['id']}/award", json={})
    assert again.status_code == 400


def test_award_is_blocked_by_an_open_po(member):
    item = item_named(member, "Phospho-Tau (pS396) Antibody")  # seeded open PO
    draft = next(q for q in _quotes(member, item) if q["status"] == "draft")
    response = member.post(f"/api/quotes/{draft['id']}/award", json={})
    assert response.status_code == 409
    assert "open PO" in response.json()["detail"]


def test_cancelling_a_po_demotes_its_quote_and_allows_re_award(member, db):
    item = item_named(member, "DMEM/F12 Medium (500 mL)")
    target = next(q for q in _quotes(member, item) if q["supplier_type"] == "alibaba")
    first = member.post(f"/api/quotes/{target['id']}/award", json={})
    assert first.status_code == 200, first.text

    cancelled = member.patch(
        f"/api/purchase-orders/{first.json()['po_id']}", json={"status": "cancelled"}
    )
    assert cancelled.status_code == 200, cancelled.text
    assert db.execute(
        "SELECT status FROM quote WHERE id = ?", (target["id"],)
    ).fetchone()[0] == "draft"

    again = member.post(f"/api/quotes/{target['id']}/award", json={})
    assert again.status_code == 200, again.text
    assert again.json()["po_id"] != first.json()["po_id"]


def test_award_demotes_stale_backup_quotes(member, db):
    item = item_named(member, "Phospho-Tau (pS396) Antibody")
    seeded = next(
        p for p in member.get("/api/purchase-orders").json() if p["item_id"] == item["id"]
    )
    assert member.patch(
        f"/api/purchase-orders/{seeded['id']}", json={"status": "cancelled"}
    ).status_code == 200

    target = next(q for q in _quotes(member, item) if q["supplier_type"] == "local_ph")
    assert member.post(f"/api/quotes/{target['id']}/award", json={}).status_code == 200

    statuses = [
        r["status"] for r in db.execute(
            "SELECT status FROM quote WHERE item_id = ?", (item["id"],)
        )
    ]
    assert statuses.count("primary") == 1
    assert statuses.count("backup") == 1


def test_award_rejects_zero_quantity_instead_of_falling_back_to_moq(member):
    item = item_named(member, "DMEM/F12 Medium (500 mL)")
    target = next(q for q in _quotes(member, item) if q["supplier_type"] == "alibaba")
    response = member.post(
        f"/api/quotes/{target['id']}/award", json={"quantity": 0}
    )
    assert response.status_code == 400


def test_out_of_range_quote_numbers_are_400(member):
    item = item_named(member, "Ethanol 70%")
    base = {
        "item_id": item["id"], "supplier_name": "Bad Input",
        "supplier_type": "local_ph", "unit_price": 10,
    }
    for bad in (
        {"fx_rate": -1}, {"shipping_php": -1}, {"cold_chain_php": -1},
        {"duty_rate": 1.5}, {"lead_time_days": -1}, {"boc_buffer_days": -1},
        {"fx_rate": 0},  # passes the model bound, must not 500 on the DB CHECK
    ):
        response = member.post("/api/quotes", json={**base, **bad})
        assert response.status_code == 400, (bad, response.text)


def test_landed_cost_ignores_client_supplied_totals(member):
    """The server computes landed cost; nothing in the request can set it."""
    item = item_named(member, "Ethanol 70%")
    response = member.post("/api/quotes", json={
        "item_id": item["id"],
        "supplier_name": "Cargo Faker",
        "supplier_type": "us_eu",
        "unit_price": 10,
        "currency": "USD",
        "fx_rate": 50,
        "moq": 2,
        "shipping_php": 100,
        "cold_chain_php": 100,
        "duty_rate": 0.05,
        "landed_cost_php": 1,
    })
    assert response.status_code == 200, response.text
    # 1000 goods + 200 freight + 60 duty + 151.20 VAT, not the supplied 1.
    assert response.json()["landed_cost_php"] == 1411.2


def test_discover_returns_three_distinct_alibaba_deals_and_marks_imports(member):
    item = item_named(member, "Ethanol 70%")
    deals = member.get(
        "/api/quotes/discover", params={"item_id": item["id"]}
    ).json()
    assert len(deals) == 3
    assert len({d["supplier_name"] for d in deals}) == 3
    assert all(d["supplier_type"] == "alibaba" and d["unit_price_php"] > 0 for d in deals)
    assert not any(d["imported"] for d in deals)

    first = deals[0]
    response = member.post("/api/quotes", json={
        "item_id": item["id"],
        "supplier_name": first["supplier_name"],
        "supplier_type": "alibaba",
        "unit_price": first["unit_price"],
        "currency": "USD",
        "fx_rate": first["fx_rate"],
        "moq": first["moq"],
        "shipping_php": first["shipping_php"],
        "cold_chain_php": first["cold_chain_php"],
        "duty_rate": first["duty_rate"],
        "lead_time_days": first["lead_time_days"],
        "boc_buffer_days": first["boc_buffer_days"],
    })
    assert response.status_code == 200, response.text

    again = member.get(
        "/api/quotes/discover", params={"item_id": item["id"]}
    ).json()
    imported = next(d for d in again if d["supplier_name"] == first["supplier_name"])
    assert imported["imported"] is True
