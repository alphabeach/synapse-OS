"""Philippine customs stages, document/permit readiness, 48h watchdog, receiving."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import alerts, audit, auth, db

router = APIRouter()

STAGES = [
    "po_placed", "shipped_awb", "pre_arrival_docs", "at_boc_filing",
    "permit_clearance", "duties_assessed", "released_in_transit", "received",
]
PERMITS = {"NONE", "FDA", "PDEA", "DENR"}
DISCREPANCIES = {"short_shipped", "damaged_cold_chain", "wrong_spec"}
DOC_FIELDS = ("doc_invoice", "doc_packing", "doc_awb", "doc_coa_msds")


class PurchaseOrderPatch(BaseModel):
    status: str | None = None
    permit_type: str | None = None
    permit_ok: bool | None = None
    doc_invoice: bool | None = None
    doc_packing: bool | None = None
    doc_awb: bool | None = None
    doc_coa_msds: bool | None = None


class ReceiveBody(BaseModel):
    lot_number: str | None = None
    expiry_date: str | None = None
    location: str | None = None
    cold_chain_ok: bool | None = None
    discrepancy: str | None = None


def _transition_ok(current, new):
    if new == current:
        return True
    if new in ("cancelled", "discrepancy_hold"):
        return current not in ("received", "cancelled")
    if current in ("received", "cancelled"):
        return False
    if current == "discrepancy_hold":
        return new in STAGES  # a hold can be cleared back into the flow
    # Normal progress is one stage at a time: no jumping the BOC queue.
    return STAGES.index(new) == STAGES.index(current) + 1


def _po_detail(conn, po_id):
    row = conn.execute(
        """SELECT p.*, i.name AS item, i.unit, q.supplier_type
             FROM purchase_order p
             JOIN item i ON i.id = p.item_id
             JOIN quote q ON q.id = p.quote_id
            WHERE p.id = ?""",
        (po_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="purchase order not found")
    po = dict(row)
    po["docs_ready"] = sum(int(po[f]) for f in DOC_FIELDS)
    po["docs_total"] = len(DOC_FIELDS)
    chase_ids = {
        c["id"]
        for c in alerts.chase(conn, alerts.int_setting(conn, "chase_hours", 48))
    }
    po["chase_required"] = po["id"] in chase_ids
    return po


@router.get("/purchase-orders")
def list_purchase_orders(user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        chase_ids = {
            c["id"]
            for c in alerts.chase(conn, alerts.int_setting(conn, "chase_hours", 48))
        }
        rows = conn.execute(
            """SELECT p.*, i.name AS item, i.unit, q.supplier_type,
                      CAST((julianday('now') - julianday(p.last_followup_at)) * 24
                           AS INTEGER) AS hours_since
                 FROM purchase_order p
                 JOIN item i ON i.id = p.item_id
                 JOIN quote q ON q.id = p.quote_id
                ORDER BY p.id DESC"""
        ).fetchall()
        out = []
        for row in rows:
            po = dict(row)
            po["docs_ready"] = sum(int(po[f]) for f in DOC_FIELDS)
            po["docs_total"] = len(DOC_FIELDS)
            po["chase_required"] = po["id"] in chase_ids
            out.append(po)
        return out
    finally:
        conn.close()


@router.get("/purchase-orders/{po_id}")
def get_purchase_order(po_id: int, user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        return _po_detail(conn, po_id)
    finally:
        conn.close()


@router.patch("/purchase-orders/{po_id}")
def update_purchase_order(po_id: int, body: PurchaseOrderPatch,
                          user: dict = Depends(auth.require_role("member"))):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    if "permit_type" in fields and fields["permit_type"] not in PERMITS:
        raise HTTPException(status_code=400, detail="unknown permit type")
    for key, value in list(fields.items()):
        if key in DOC_FIELDS or key == "permit_ok":
            fields[key] = int(value)
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="purchase order not found")
        current = row["status"]
        if "status" in fields:
            new = fields["status"]
            if new == "received":
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail="use /receive so a lot with lot number and expiry is minted",
                )
            if new not in STAGES and new not in ("discrepancy_hold", "cancelled"):
                conn.rollback()
                raise HTTPException(status_code=400, detail="unknown status")
            if not _transition_ok(current, new):
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"cannot move a {current} order to {new}",
                )
            if new == "released_in_transit":
                # The release gate: every document plus the permit when the
                # item needs one. Docs patched in this same request count.
                state = dict(row)
                state.update(fields)
                missing = [f for f in DOC_FIELDS if not state[f]]
                if state["permit_type"] != "NONE" and not state["permit_ok"]:
                    missing.append("permit_ok")
                if missing:
                    conn.rollback()
                    raise HTTPException(
                        status_code=400,
                        detail="released_in_transit requires " + ", ".join(missing),
                    )
            if new == "cancelled":
                # Put the quote back on the bench so the item can be re-awarded.
                conn.execute(
                    "UPDATE quote SET status = 'draft' WHERE id = ? AND status = 'primary'",
                    (row["quote_id"],),
                )
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE purchase_order SET {sets} WHERE id = ?",
                     (*fields.values(), po_id))
        audit.record(conn, user, "po.update", "purchase_order", po_id,
                     ", ".join(sorted(fields)))
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


@router.post("/purchase-orders/{po_id}/followup")
def log_followup(po_id: int, user: dict = Depends(auth.require_role("member"))):
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT status FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="purchase order not found")
        if row["status"] in ("received", "cancelled"):
            raise HTTPException(status_code=400, detail="order is closed")
        conn.execute(
            "UPDATE purchase_order SET last_followup_at = datetime('now') WHERE id = ?",
            (po_id,),
        )
        audit.record(conn, user, "po.followup", "purchase_order", po_id,
                     "chased broker/supplier")
        conn.commit()
        return _po_detail(conn, po_id)
    finally:
        conn.close()


@router.post("/purchase-orders/{po_id}/receive")
def receive_purchase_order(po_id: int, body: ReceiveBody,
                           user: dict = Depends(auth.require_role("member"))):
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        po = conn.execute(
            "SELECT * FROM purchase_order WHERE id = ?", (po_id,)
        ).fetchone()
        if po is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="purchase order not found")
        if po["status"] == "received":
            conn.rollback()
            raise HTTPException(status_code=400, detail="order already received")
        if po["status"] == "cancelled":
            conn.rollback()
            raise HTTPException(status_code=400, detail="order was cancelled")

        if body.discrepancy:
            if body.discrepancy not in DISCREPANCIES:
                conn.rollback()
                raise HTTPException(status_code=400, detail="unknown discrepancy")
            conn.execute(
                """UPDATE purchase_order
                      SET status = 'discrepancy_hold', discrepancy = ?
                    WHERE id = ?""",
                (body.discrepancy, po_id),
            )
            audit.record(conn, user, "po.discrepancy", "purchase_order", po_id,
                         body.discrepancy)
            conn.commit()
            return {"ok": True, "status": "discrepancy_hold",
                    "detail": _po_detail(conn, po_id)}

        missing = [
            name for name, value in (
                ("lot_number", body.lot_number),
                ("expiry_date", body.expiry_date),
                ("location", body.location),
                ("cold_chain_ok", body.cold_chain_ok),
            ) if value is None or value == ""
        ]
        if missing:
            conn.rollback()
            raise HTTPException(
                status_code=400,
                detail="receiving requires " + ", ".join(missing),
            )
        try:
            expiry = date.fromisoformat(body.expiry_date).isoformat()
        except ValueError:
            conn.rollback()
            raise HTTPException(status_code=400, detail="expiry_date must be YYYY-MM-DD")

        lot_id = conn.execute(
            """INSERT INTO lot (item_id, po_id, lot_number, expiry_date, quantity,
                                location, cold_chain_ok, received_date)
               VALUES (?, ?, ?, ?, ?, ?, ?, date('now', '+8 hours'))""",
            (po["item_id"], po_id, body.lot_number.strip(), expiry, po["quantity"],
             body.location.strip(), int(bool(body.cold_chain_ok))),
        ).lastrowid
        conn.execute(
            "UPDATE item SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?",
            (po["quantity"], po["item_id"]),
        )
        conn.execute(
            """UPDATE purchase_order
                  SET status = 'received',
                      received_at = datetime('now', '+8 hours'),
                      cold_chain_ok = ?
                WHERE id = ?""",
            (int(bool(body.cold_chain_ok)), po_id),
        )
        audit.record(
            conn, user, "po.receive", "purchase_order", po_id,
            f"lot {body.lot_number.strip()} exp {expiry} +{po['quantity']}",
        )
        conn.commit()
        return {
            "ok": True,
            "status": "received",
            "lot_id": lot_id,
            "quantity": po["quantity"],
            "item_id": po["item_id"],
        }
    finally:
        conn.close()
