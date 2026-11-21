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
