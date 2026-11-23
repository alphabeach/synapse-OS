"""Multi-supplier quote matrix (PHP landed cost) and atomic award -> PO."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import audit, auth, db, landed

router = APIRouter()

SUPPLIER_TYPES = {"local_ph", "alibaba", "wechat", "us_eu"}
CURRENCIES = {"PHP", "USD"}
MAX_QTY = 1_000_000
MAX_DAYS = 3_650
MAX_MONEY = 10_000_000
MAX_FX = 1_000

# Static Alibaba offers used by the deal finder. Prices scale with the item's
# local unit cost so the demo stays plausible for any item. The supplier names
# are stable keys: a quote already carrying the name is marked imported.
ALIBABA_DEALS = [
    ("Alibaba - SinoBio Reagents", 0.25, 2, 1800, 2600, 0.05, 18, 7),
    ("Alibaba - Hangzhou BioSupply", 0.31, 5, 1500, 2400, 0.05, 21, 7),
    ("Alibaba - Shanghai LabTech", 0.38, 1, 2100, 2800, 0.03, 14, 5),
]
DISCOVER_FX = 58.5


class QuoteBody(BaseModel):
    item_id: int
    supplier_name: str
    supplier_type: str
    unit_price: float
    currency: str = "PHP"
    fx_rate: float = Field(1, ge=0, le=MAX_FX)
    moq: int = 1
    shipping_php: float = Field(0, ge=0, le=MAX_MONEY)
    cold_chain_php: float = Field(0, ge=0, le=MAX_MONEY)
    duty_rate: float = Field(0, ge=0, le=1.0)
    lead_time_days: int = Field(0, ge=0, le=MAX_DAYS)
    boc_buffer_days: int = Field(0, ge=0, le=MAX_DAYS)
    note: str | None = None


class AwardBody(BaseModel):
    quantity: int | None = None


def decorate(row, quantity=None):
    """Add the PHP landed cost and bench lead time. One calculation, one place."""
    quote = dict(row)
    qty = quantity or quote["moq"]
    quote["unit_price_php"] = round(
        quote["unit_price"] * (quote["fx_rate"] if quote["currency"] == "USD" else 1),
        2,
    )
    quote["landed_cost_php"] = landed.landed_cost(
        quote["unit_price"], quote["currency"], quote["fx_rate"], qty,
        quote["shipping_php"], quote["cold_chain_php"], quote["duty_rate"],
    )
    quote["effective_lead_days"] = landed.effective_lead_days(
        quote["lead_time_days"], quote["boc_buffer_days"]
    )
    quote["landed_for_qty"] = qty
    return quote


@router.get("/quotes")
def list_quotes(item_id: int | None = None,
                user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        sql = """SELECT q.*, i.name AS item FROM quote q JOIN item i ON i.id = q.item_id"""
        params = []
        if item_id is not None:
            sql += " WHERE q.item_id = ?"
            params.append(item_id)
        sql += """ ORDER BY q.item_id,
                   CASE q.status WHEN 'primary' THEN 0 WHEN 'backup' THEN 1
                                 WHEN 'draft' THEN 2 ELSE 3 END, q.id"""
        out = [decorate(r) for r in conn.execute(sql, params)]
        out.sort(key=lambda q: (q["item_id"], q["landed_cost_php"]))
        return out
    finally:
        conn.close()


@router.get("/quotes/discover")
def discover_quotes(item_id: int | None = None,
                    user: dict = Depends(auth.require_role("viewer"))):
    """Three distinct Alibaba offers for an item, priced in PHP landed cost."""
    conn = db.get_conn()
    try:
        sql = "SELECT id, name, unit_cost_php FROM item"
        params = []
        if item_id is not None:
            sql += " WHERE id = ?"
            params.append(item_id)
        sql += " ORDER BY id LIMIT 1"
        item = conn.execute(sql, params).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")

        existing = {
            row["supplier_name"] for row in conn.execute(
                """SELECT supplier_name FROM quote
                    WHERE item_id = ? AND supplier_type = 'alibaba'""",
                (item["id"],),
            )
        }
        deals = []
        for name, factor, moq, ship, cold, duty, lead, buffer in ALIBABA_DEALS:
            price = round(max(item["unit_cost_php"], 1) * factor / DISCOVER_FX, 2)
            deal = decorate({
                "item_id": item["id"], "supplier_name": name,
                "supplier_type": "alibaba", "unit_price": price,
                "currency": "USD", "fx_rate": DISCOVER_FX, "moq": moq,
                "shipping_php": ship, "cold_chain_php": cold,
                "duty_rate": duty, "lead_time_days": lead,
                "boc_buffer_days": buffer,
            })
            deal["item"] = item["name"]
            deal["imported"] = name in existing
            deals.append(deal)
        return deals
    finally:
        conn.close()


@router.post("/quotes")
def create_quote(body: QuoteBody, user: dict = Depends(auth.require_role("member"))):
    if not body.supplier_name.strip():
        raise HTTPException(status_code=400, detail="supplier name is required")
    if body.supplier_type not in SUPPLIER_TYPES:
        raise HTTPException(status_code=400, detail="unknown supplier type")
    if body.currency not in CURRENCIES:
        raise HTTPException(status_code=400, detail="currency must be PHP or USD")
    if body.unit_price <= 0:
        raise HTTPException(status_code=400, detail="unit price must be positive")
    if not 0 < body.moq <= MAX_QTY:
        raise HTTPException(status_code=400, detail="MOQ out of range")
    conn = db.get_conn()
    try:
        if conn.execute("SELECT 1 FROM item WHERE id = ?", (body.item_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="item not found")
        quote_id = conn.execute(
            """INSERT INTO quote
                   (item_id, supplier_name, supplier_type, unit_price, currency,
                    fx_rate, moq, shipping_php, cold_chain_php, duty_rate,
                    lead_time_days, boc_buffer_days, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.item_id, body.supplier_name.strip(), body.supplier_type,
             body.unit_price, body.currency, body.fx_rate, body.moq,
             body.shipping_php, body.cold_chain_php, body.duty_rate,
             body.lead_time_days, body.boc_buffer_days, body.note),
        ).lastrowid
        audit.record(conn, user, "quote.create", "quote", quote_id,
                     f"{body.supplier_name.strip()} for item {body.item_id}")
        conn.commit()
        row = conn.execute(
            """SELECT q.*, i.name AS item FROM quote q JOIN item i ON i.id = q.item_id
                WHERE q.id = ?""",
            (quote_id,),
        ).fetchone()
        return decorate(row)
    finally:
        conn.close()


@router.post("/quotes/{quote_id}/award")
def award_quote(quote_id: int, body: AwardBody,
                user: dict = Depends(auth.require_role("member"))):
    """Mark one quote primary, the cheapest rival backup, and create the PO."""
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        quote = conn.execute(
            """SELECT q.*, i.name AS item FROM quote q JOIN item i ON i.id = q.item_id
                WHERE q.id = ?""",
            (quote_id,),
        ).fetchone()
        if quote is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="quote not found")
        if quote["status"] == "rejected":
            conn.rollback()
            raise HTTPException(status_code=400, detail="quote was rejected")
        if quote["status"] == "primary":
            conn.rollback()
            raise HTTPException(status_code=400, detail="quote is already awarded")

        quantity = body.quantity if body.quantity is not None else quote["moq"]
        if not 0 < quantity <= MAX_QTY:
            conn.rollback()
            raise HTTPException(status_code=400, detail="quantity out of range")

        open_po = conn.execute(
            """SELECT id FROM purchase_order
                WHERE item_id = ? AND status NOT IN ('received', 'cancelled')""",
            (quote["item_id"],),
        ).fetchone()
        if open_po is not None:
            conn.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"item already has open PO #{open_po['id']}",
            )

        # Runner-up: the cheapest other live quote for the same item.
        rivals = [
            r for r in conn.execute(
                """SELECT * FROM quote
                    WHERE item_id = ? AND id <> ? AND status <> 'rejected'""",
                (quote["item_id"], quote_id),
            )
        ]
        rivals.sort(key=lambda r: landed.landed_cost(
            r["unit_price"], r["currency"], r["fx_rate"], r["moq"],
            r["shipping_php"], r["cold_chain_php"], r["duty_rate"],
        ))

        # A new award replaces the whole bench, so no stale backup survives it.
        conn.execute(
            """UPDATE quote SET status = 'draft'
                WHERE item_id = ? AND status IN ('primary', 'backup')""",
            (quote["item_id"],),
        )
        conn.execute("UPDATE quote SET status = 'primary' WHERE id = ?", (quote_id,))
        if rivals:
            conn.execute("UPDATE quote SET status = 'backup' WHERE id = ?",
                         (rivals[0]["id"],))

        cost = landed.landed_cost(
            quote["unit_price"], quote["currency"], quote["fx_rate"], quantity,
            quote["shipping_php"], quote["cold_chain_php"], quote["duty_rate"],
        )
        po_id = conn.execute(
            """INSERT INTO purchase_order
                   (quote_id, item_id, supplier_name, is_import, quantity,
                    landed_cost_php, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (quote_id, quote["item_id"], quote["supplier_name"],
             0 if quote["supplier_type"] == "local_ph" else 1,
             quantity, cost, user["id"]),
        ).lastrowid
        audit.record(
            conn, user, "quote.award", "quote", quote_id,
            f"{quote['supplier_name']} -> PO #{po_id}, PHP {cost}",
        )
        conn.commit()
        return {
            "po_id": po_id,
            "quote_id": quote_id,
            "item": quote["item"],
            "quantity": quantity,
            "landed_cost_php": cost,
            "backup_quote_id": rivals[0]["id"] if rivals else None,
        }
    finally:
        conn.close()
