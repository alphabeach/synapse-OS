"""Inventory: items, lots, guarded consumption, FEFO drain, recount, dashboard."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import alerts, audit, auth, db

router = APIRouter()

MAX_QTY = 1_000_000
MAX_DAYS = 3_650
MAX_RATE = 1_000_000
MAX_COST = 100_000_000
CATEGORIES = {"antibody", "reagent", "media", "chemical", "consumable", "other"}
STATUSES = {"active", "deprecated"}


class ItemBody(BaseModel):
    name: str
    category: str = "other"
    unit: str = "vial"
    quantity_on_hand: int = Field(0, ge=0, le=MAX_QTY)
    daily_burn_rate: float = Field(0, ge=0, le=MAX_RATE)
    safety_stock: int = Field(0, ge=0, le=MAX_QTY)
    lead_time_days: int = Field(0, ge=0, le=MAX_DAYS)
    unit_cost_php: float = Field(0, ge=0, le=MAX_COST)


class ItemPatch(BaseModel):
    name: str | None = None
    category: str | None = None
    unit: str | None = None
    daily_burn_rate: float | None = Field(None, ge=0, le=MAX_RATE)
    safety_stock: int | None = Field(None, ge=0, le=MAX_QTY)
    lead_time_days: int | None = Field(None, ge=0, le=MAX_DAYS)
    unit_cost_php: float | None = Field(None, ge=0, le=MAX_COST)
    status: str | None = None


class ConsumeBody(BaseModel):
    quantity: int
    note: str | None = None


class RestockBody(BaseModel):
    quantity: int
    lot_number: str
    expiry_date: str
    location: str
    cold_chain_ok: bool = True


class RecountBody(BaseModel):
    expected_quantity: int
    quantity: int
    reason: str | None = None


def like_term(term: str) -> str:
    """Escape SQL wildcards so a search for '100%' matches a literal percent."""
    for ch in ("\\", "%", "_"):
        term = term.replace(ch, "\\" + ch)
    return f"%{term}%"


def _valid_expiry(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="expiry_date must be YYYY-MM-DD")


def _item_json(conn, item_id):
    row = conn.execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="item not found")
    buffer_days = alerts.int_setting(conn, "boc_buffer_days", 7)
    item = dict(row)
    location = conn.execute(
        """SELECT location FROM lot
            WHERE item_id = ? AND quantity > 0
            ORDER BY expiry_date, id LIMIT 1""",
        (item_id,),
    ).fetchone()
    item["storage_location"] = location["location"] if location else None
    item["reorder_level"] = alerts.reorder_level(
        item["daily_burn_rate"], item["lead_time_days"],
        item["safety_stock"], buffer_days,
    )
    item["low"] = item["status"] == "active" and item["quantity_on_hand"] <= item["reorder_level"]
    return item


def _draw_down_fefo(conn, item_id, quantity):
    """Mirror a decrement onto lots, earliest expiry first.

    Each lot update is guarded. shortcut: if the lots do not add up to the
    item total, the total (already decremented) stays authoritative and the
    remainder is simply unallocated; upgrade by recounting at lot level.
    """
    remaining = quantity
    for lot in conn.execute(
        """SELECT id, quantity FROM lot
            WHERE item_id = ? AND quantity > 0
            ORDER BY expiry_date, id""",
        (item_id,),
    ):
        take = min(lot["quantity"], remaining)
        conn.execute(
            "UPDATE lot SET quantity = quantity - ? WHERE id = ? AND quantity >= ?",
            (take, lot["id"], take),
        )
        remaining -= take
        if remaining <= 0:
            return


def _sync_lots(conn, item_id, new_quantity):
    """Make SUM(lot.quantity) equal the recounted item total.

    A decrease drains real lots FEFO. An increase is stock nobody labelled, so
    it becomes one adjustment lot with a far expiry: no real batch is invented
    and the count never shows as expiring.
    """
    lot_total = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) FROM lot WHERE item_id = ?", (item_id,)
    ).fetchone()[0]
    if new_quantity < lot_total:
        _draw_down_fefo(conn, item_id, lot_total - new_quantity)
    elif new_quantity > lot_total:
        conn.execute(
            """INSERT INTO lot (item_id, lot_number, expiry_date, quantity,
                                location, cold_chain_ok, received_date)
               VALUES (?, 'ADJ-' || date('now', '+8 hours'),
                       date('now', '+8 hours', '+10 years'), ?,
                       'Recount adjustment', 1, date('now', '+8 hours'))""",
            (item_id, new_quantity - lot_total),
        )


@router.get("/items")
def list_items(q: str | None = None, user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        buffer_days = alerts.int_setting(conn, "boc_buffer_days", 7)
        sql = """SELECT i.*, (
                     SELECT l.location FROM lot l
                      WHERE l.item_id = i.id AND l.quantity > 0
                      ORDER BY l.expiry_date, l.id LIMIT 1
                 ) AS storage_location
                   FROM item i"""
        params = []
        if q:
            sql += " WHERE i.name LIKE ? ESCAPE '\\'"
            params.append(like_term(q))
        sql += " ORDER BY i.status = 'deprecated', i.name"
        out = []
        for row in conn.execute(sql, params):
            item = dict(row)
            item["reorder_level"] = alerts.reorder_level(
                item["daily_burn_rate"], item["lead_time_days"],
                item["safety_stock"], buffer_days,
            )
            item["low"] = (
                item["status"] == "active"
                and item["quantity_on_hand"] <= item["reorder_level"]
            )
            out.append(item)
        return out
    finally:
        conn.close()


@router.get("/items/{item_id}")
def item_detail(item_id: int, user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        item = _item_json(conn, item_id)
        item["lots"] = [
            dict(r) for r in conn.execute(
                """SELECT id, lot_number, expiry_date, quantity, location,
                          cold_chain_ok, received_date
                     FROM lot WHERE item_id = ?
                    ORDER BY expiry_date""",
                (item_id,),
            )
        ]
        return item
    finally:
        conn.close()


@router.post("/items")
def create_item(body: ItemBody, user: dict = Depends(auth.require_role("admin"))):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="name is required")
    if body.category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="unknown category")
    if not 0 <= body.quantity_on_hand <= MAX_QTY:
        raise HTTPException(status_code=400, detail="quantity out of range")
    conn = db.get_conn()
    try:
        item_id = conn.execute(
            """INSERT INTO item (name, category, unit, quantity_on_hand,
                                 daily_burn_rate, safety_stock, lead_time_days,
                                 unit_cost_php)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.name.strip(), body.category, body.unit, body.quantity_on_hand,
             body.daily_burn_rate, body.safety_stock, body.lead_time_days,
             body.unit_cost_php),
        ).lastrowid
        audit.record(conn, user, "item.create", "item", item_id, body.name.strip())
        conn.commit()
        return _item_json(conn, item_id)
    finally:
        conn.close()


@router.patch("/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch,
               user: dict = Depends(auth.require_role("admin"))):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    if "category" in fields and fields["category"] not in CATEGORIES:
        raise HTTPException(status_code=400, detail="unknown category")
    if "status" in fields and fields["status"] not in STATUSES:
        raise HTTPException(status_code=400, detail="unknown status")
    if "name" in fields and not str(fields["name"]).strip():
        raise HTTPException(status_code=400, detail="name cannot be empty")
    conn = db.get_conn()
    try:
        if conn.execute("SELECT 1 FROM item WHERE id = ?", (item_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="item not found")
        sets = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE item SET {sets} WHERE id = ?", (*fields.values(), item_id))
        audit.record(conn, user, "item.update", "item", item_id,
                     ", ".join(sorted(fields)))
        conn.commit()
        return _item_json(conn, item_id)
    finally:
        conn.close()


@router.post("/items/{item_id}/consume")
def consume(item_id: int, body: ConsumeBody,
            user: dict = Depends(auth.require_role("member"))):
    if not 0 < body.quantity <= MAX_QTY:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # The guard is the whole concurrency story: exactly one writer can take
        # stock from 2 to 1, and nobody can take it below zero.
        cur = conn.execute(
            """UPDATE item SET quantity_on_hand = quantity_on_hand - ?
                WHERE id = ? AND quantity_on_hand >= ? AND status = 'active'""",
            (body.quantity, item_id, body.quantity),
        )
        if cur.rowcount == 0:
            conn.rollback()
            row = conn.execute(
                "SELECT quantity_on_hand, status FROM item WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="item not found")
            if row["status"] != "active":
                raise HTTPException(status_code=400, detail="item is deprecated")
            raise HTTPException(
                status_code=400,
                detail=f"insufficient stock: {row['quantity_on_hand']} on hand",
            )
        _draw_down_fefo(conn, item_id, body.quantity)
        detail = f"-{body.quantity}" + (f" ({body.note})" if body.note else "")
        audit.record(conn, user, "stock.consume", "item", item_id, detail)
        conn.commit()
        return _item_json(conn, item_id)
    finally:
        conn.close()


@router.post("/items/{item_id}/restock")
def restock(item_id: int, body: RestockBody,
            user: dict = Depends(auth.require_role("member"))):
    if not 0 < body.quantity <= MAX_QTY:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    expiry = _valid_expiry(body.expiry_date)
    if not body.lot_number.strip() or not body.location.strip():
        raise HTTPException(status_code=400, detail="lot number and location are required")
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM item WHERE id = ?", (item_id,)).fetchone() is None:
            conn.rollback()
            raise HTTPException(status_code=404, detail="item not found")
        lot_id = conn.execute(
            """INSERT INTO lot (item_id, lot_number, expiry_date, quantity,
                                location, cold_chain_ok, received_date)
               VALUES (?, ?, ?, ?, ?, ?, date('now', '+8 hours'))""",
            (item_id, body.lot_number.strip(), expiry, body.quantity,
             body.location.strip(), int(body.cold_chain_ok)),
        ).lastrowid
        conn.execute(
            "UPDATE item SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?",
            (body.quantity, item_id),
        )
        audit.record(conn, user, "stock.restock", "item", item_id,
                     f"+{body.quantity} lot {body.lot_number}")
        conn.commit()
        return {"ok": True, "lot_id": lot_id, "item": _item_json(conn, item_id)}
    finally:
        conn.close()


@router.post("/items/{item_id}/recount")
def recount(item_id: int, body: RecountBody,
            user: dict = Depends(auth.require_role("member"))):
    if not 0 <= body.quantity <= MAX_QTY:
        raise HTTPException(status_code=400, detail="quantity out of range")
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Optimistic lock: only apply if nobody changed the stock since the
        # client read it. Otherwise the user is looking at stale data.
        cur = conn.execute(
            """UPDATE item SET quantity_on_hand = ?
                WHERE id = ? AND quantity_on_hand = ?""",
            (body.quantity, item_id, body.expected_quantity),
        )
        if cur.rowcount == 0:
            conn.rollback()
            row = conn.execute(
                "SELECT quantity_on_hand FROM item WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="item not found")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"stock changed: {row['quantity_on_hand']} on hand now, "
                    f"you expected {body.expected_quantity}. Refresh and retry."
                ),
            )
        _sync_lots(conn, item_id, body.quantity)
        audit.record(
            conn, user, "stock.recount", "item", item_id,
            f"{body.expected_quantity} -> {body.quantity}"
            + (f" ({body.reason})" if body.reason else ""),
        )
        conn.commit()
        return _item_json(conn, item_id)
    finally:
        conn.close()


@router.get("/dashboard")
def dashboard(user: dict = Depends(auth.require_role("viewer"))):
    conn = db.get_conn()
    try:
        return alerts.attention(conn)
    finally:
        conn.close()
