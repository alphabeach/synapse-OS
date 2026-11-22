"""The single source of truth for the dashboard counters and alert bar.

Every consumer (dashboard counters, alert bar, purchase-order chase badges)
calls these functions, so the numbers can never disagree with the badges.
Everything here is read-only: a GET never takes a write lock or reconciles state.
"""
import math


def int_setting(conn, key, default):
    row = conn.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
    try:
        return int(row["value"]) if row else default
    except (TypeError, ValueError):
        return default


def reorder_level(daily_burn_rate, lead_time_days, safety_stock, buffer_days):
    """Customs-buffered reorder point: ceil(burn * (lead + BOC buffer) + safety)."""
    return math.ceil(
        float(daily_burn_rate) * (int(lead_time_days) + int(buffer_days))
        + int(safety_stock)
    )


def low_stock(conn, buffer_days):
    out = []
    for r in conn.execute(
        """SELECT id, name, unit, quantity_on_hand, daily_burn_rate,
                  safety_stock, lead_time_days
             FROM item WHERE status = 'active'"""
    ):
        level = reorder_level(
            r["daily_burn_rate"], r["lead_time_days"], r["safety_stock"], buffer_days
        )
        if r["quantity_on_hand"] <= level:
            out.append({
                "item_id": r["id"],
                "item": r["name"],
                "unit": r["unit"],
                "quantity": r["quantity_on_hand"],
                "reorder_level": level,
            })
    out.sort(key=lambda x: x["quantity"] - x["reorder_level"])
    return out


def expiring(conn):
    rows = conn.execute(
        """SELECT l.id AS lot_id, l.lot_number, l.expiry_date, l.quantity,
                  i.id AS item_id, i.name AS item
             FROM lot l JOIN item i ON i.id = l.item_id
            WHERE l.quantity > 0 AND i.status = 'active'
              AND l.expiry_date <= date('now', '+8 hours', '+30 day')
            ORDER BY l.expiry_date, l.id"""
    ).fetchall()
    return [dict(r) for r in rows]


def chase(conn, hours):
    """Active import shipments silent for >= `hours` since the last follow-up."""
    rows = conn.execute(
        """SELECT p.id, p.supplier_name, p.status, i.name AS item,
                  CAST((julianday('now') - julianday(p.last_followup_at)) * 24 AS INTEGER)
                      AS hours_since
             FROM purchase_order p JOIN item i ON i.id = p.item_id
            WHERE p.is_import = 1
              AND p.status NOT IN ('received', 'cancelled')
              AND (julianday('now') - julianday(p.last_followup_at)) * 24 >= ?
            ORDER BY hours_since DESC""",
        (hours,),
    ).fetchall()
    return [dict(r) for r in rows]


def attention(conn):
    buffer_days = int_setting(conn, "boc_buffer_days", 7)
    chase_hours = int_setting(conn, "chase_hours", 48)

    low = low_stock(conn, buffer_days)
    exp = expiring(conn)
    ch = chase(conn, chase_hours)

    open_pos = conn.execute(
        "SELECT COUNT(*) FROM purchase_order WHERE status NOT IN ('received', 'cancelled')"
    ).fetchone()[0]
    spend = conn.execute(
        "SELECT COALESCE(SUM(landed_cost_php), 0) FROM purchase_order WHERE status = 'received'"
    ).fetchone()[0]

    return {
        "low_stock": low,
        "expiring": exp,
        "chase": ch,
        "counts": {
            "active_items": conn.execute(
                "SELECT COUNT(*) FROM item WHERE status = 'active'"
            ).fetchone()[0],
            "low_stock": len(low),
            "expiring": len(exp),
            "chase": len(ch),
            "open_pos": open_pos,
            "spend_php": round(spend, 2),
        },
    }
