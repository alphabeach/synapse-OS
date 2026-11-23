"""Customs stages, the 48h watchdog, and lot-captured receiving."""
from tests.conftest import item_named


def _seeded_po(client):
    orders = client.get("/api/purchase-orders").json()
    assert orders
    return orders[0]


def test_seeded_shipment_is_past_the_48h_watchdog(member):
    po = _seeded_po(member)
    assert po["status"] == "at_boc_filing"
    assert po["chase_required"] is True
    assert po["hours_since"] >= 48


def test_dashboard_count_and_badges_use_the_same_predicate(member):
    data = member.get("/api/dashboard").json()
    orders = member.get("/api/purchase-orders").json()
    assert data["counts"]["chase"] == sum(1 for p in orders if p["chase_required"])


def test_followup_clears_the_badge(member):
    po = _seeded_po(member)
    assert member.post(f"/api/purchase-orders/{po['id']}/followup").status_code == 200
    refreshed = member.get(f"/api/purchase-orders/{po['id']}").json()
    assert refreshed["chase_required"] is False
    assert member.get("/api/dashboard").json()["counts"]["chase"] == 0


def test_receive_requires_lot_expiry_location(member):
    po = _seeded_po(member)
    response = member.post(
        f"/api/purchase-orders/{po['id']}/receive", json={"lot_number": "L1"}
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "expiry_date" in detail and "location" in detail


def test_receive_mints_lot_and_increments_stock(member, db):
    po = _seeded_po(member)
    before = db.execute(
        "SELECT quantity_on_hand FROM item WHERE id = ?", (po["item_id"],)
    ).fetchone()[0]

    response = member.post(f"/api/purchase-orders/{po['id']}/receive", json={
        "lot_number": "PT396-2502",
        "expiry_date": "2027-06-30",
        "location": "Lab -80C Freezer F2 / Box 4",
        "cold_chain_ok": True,
    })
    assert response.status_code == 200, response.text

    lot = db.execute(
        "SELECT * FROM lot WHERE po_id = ?", (po["id"],)
    ).fetchone()
    assert lot["lot_number"] == "PT396-2502"
    assert lot["expiry_date"] == "2027-06-30"
    assert lot["quantity"] == po["quantity"]

    after = db.execute(
        "SELECT quantity_on_hand FROM item WHERE id = ?", (po["item_id"],)
    ).fetchone()[0]
    assert after == before + po["quantity"]

    # A second receipt must not mint a duplicate lot.
    again = member.post(f"/api/purchase-orders/{po['id']}/receive", json={
        "lot_number": "PT396-2502", "expiry_date": "2027-06-30",
        "location": "Lab -80C Freezer F2 / Box 4", "cold_chain_ok": True,
    })
    assert again.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM lot WHERE po_id = ?", (po["id"],)
    ).fetchone()[0] == 1

    assert db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'po.receive' AND entity_id = ?",
        (po["id"],),
    ).fetchone()[0] == 1


def test_discrepancy_opens_a_hold_without_minting_a_lot(member, db):
    po = _seeded_po(member)
    response = member.post(
        f"/api/purchase-orders/{po['id']}/receive",
        json={"discrepancy": "damaged_cold_chain"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "discrepancy_hold"
    assert db.execute(
        "SELECT COUNT(*) FROM lot WHERE po_id = ?", (po["id"],)
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT status FROM purchase_order WHERE id = ?", (po["id"],)
    ).fetchone()[0] == "discrepancy_hold"


def test_patch_cannot_skip_receiving(member):
    po = _seeded_po(member)
    response = member.patch(
        f"/api/purchase-orders/{po['id']}", json={"status": "received"}
    )
    assert response.status_code == 400
    assert "receive" in response.json()["detail"]


def test_stage_moves_forward_and_docs_are_tracked(member):
    po = _seeded_po(member)
    response = member.patch(f"/api/purchase-orders/{po['id']}", json={
        "status": "permit_clearance",
        "doc_coa_msds": True,
        "permit_ok": True,
    })
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "permit_clearance"
    assert updated["doc_coa_msds"] == 1
    assert updated["docs_ready"] == 4

    backwards = member.patch(
        f"/api/purchase-orders/{po['id']}", json={"status": "shipped_awb"}
    )
    assert backwards.status_code == 400


def test_stage_advance_must_be_one_step(member):
    po = _seeded_po(member)  # at_boc_filing
    skipped = member.patch(
        f"/api/purchase-orders/{po['id']}", json={"status": "duties_assessed"}
    )
    assert skipped.status_code == 400
    assert member.patch(
        f"/api/purchase-orders/{po['id']}", json={"status": "permit_clearance"}
    ).status_code == 200


def test_released_in_transit_requires_all_docs_and_permit(member):
    po = _seeded_po(member)
    url = f"/api/purchase-orders/{po['id']}"
    assert member.patch(url, json={"status": "permit_clearance"}).status_code == 200
    assert member.patch(url, json={"status": "duties_assessed"}).status_code == 200

    blocked = member.patch(url, json={"status": "released_in_transit"})
    assert blocked.status_code == 400
    assert "doc_coa_msds" in blocked.json()["detail"]
    assert "permit_ok" in blocked.json()["detail"]

    permit_only = member.patch(
        url, json={"status": "released_in_transit", "permit_ok": True}
    )
    assert permit_only.status_code == 400
    assert "doc_coa_msds" in permit_only.json()["detail"]

    docs_only = member.patch(
        url, json={"status": "released_in_transit", "doc_coa_msds": True}
    )
    assert docs_only.status_code == 400
    assert "permit_ok" in docs_only.json()["detail"]

    released = member.patch(url, json={
        "status": "released_in_transit", "doc_coa_msds": True, "permit_ok": True,
    })
    assert released.status_code == 200, released.text


def test_viewer_sees_orders_but_cannot_change_them(viewer):
    po = _seeded_po(viewer)
    assert viewer.post(f"/api/purchase-orders/{po['id']}/followup").status_code == 403
    assert viewer.patch(
        f"/api/purchase-orders/{po['id']}", json={"permit_ok": True}
    ).status_code == 403
