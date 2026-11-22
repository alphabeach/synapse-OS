"""Realistic BGC neuro-lab demo data, seeded once when the database is empty.

Dates are relative (date('now', ...)) so the demo never looks stale: one lot is
always 18 days from expiry and one BOC shipment is always 3 days past its
follow-up, which makes every alert visible on first boot.
"""
import os

from app import audit, auth, db, landed

# The one place the demo credentials live: seeding and POST /api/demo-login both
# read these, so they cannot drift apart.
DEMO_ACCOUNT = {"username": "admin", "password": "exin-demo-2026"}
DEMO_PASSWORDS = {
    "admin": DEMO_ACCOUNT["password"],
    "member": "exin-member-2026",
    "viewer": "exin-viewer-2026",
}


def demo_login_enabled() -> bool:
    """Demo accounts are on by default locally; DEMO_LOGIN=0 turns them off."""
    return os.environ.get("DEMO_LOGIN", "1") == "1"

_USERS = [
    ("admin", "Exin Admin", "admin"),
    ("member", "Procurement Officer", "member"),
    ("viewer", "Lab Viewer", "viewer"),
]

_ITEMS = [
    # name, category, unit, qty, burn/day, safety, lead days, unit cost PHP
    ("Phospho-Tau (pS396) Antibody", "antibody", "vial", 2, 0.05, 1, 14, 52000),
    ("DMEM/F12 Medium (500 mL)", "media", "bottle", 6, 0.25, 4, 10, 4200),
    ("B-27 Supplement (50x)", "reagent", "vial", 3, 0.08, 2, 14, 9800),
    ("Lipofectamine 3000", "reagent", "vial", 1, 0.04, 1, 21, 28500),
    ("Filtered Pipette Tips 200 uL", "consumable", "rack", 40, 1.5, 20, 5, 850),
    ("Ethanol 70%", "chemical", "bottle", 10, 0.3, 5, 5, 620),
]

# item index, supplier, type, unit price, currency, fx, moq, freight PHP,
# cold-chain PHP, duty rate, lead days, BOC buffer, status
_QUOTES = [
    (0, "Biomedika PH", "local_ph", 42000, "PHP", 1, 1, 500, 1500, 0.0, 5, 0, "draft"),
    (0, "Cell Signaling Technology (US)", "us_eu", 520, "USD", 58.5, 1, 3500, 4200, 0.03, 10, 5, "backup"),
    (0, "Alibaba - BioReagents CN", "alibaba", 210, "USD", 58.5, 2, 1800, 2600, 0.05, 18, 7, "primary"),
    (1, "Biomedika PH", "local_ph", 4200, "PHP", 1, 1, 300, 800, 0.0, 5, 0, "draft"),
    (1, "Alibaba - BioReagents CN", "alibaba", 42, "USD", 58.5, 6, 1800, 2600, 0.05, 18, 7, "draft"),
]

# item index, lot number, expiry offset, qty, BGC location, cold chain intact
_LOTS = [
    (0, "PT396-2411", "+120 day", 2, "BGC -80C Freezer F2 / Rack A / Box 3", 1),
    (1, "DMF12-8842", "+60 day", 6, "BGC 4C Fridge / Shelf 2", 1),
    (2, "B27-5521", "+18 day", 3, "BGC -20C Freezer F1 / Box 7", 1),
    (3, "L3000-7731", "+200 day", 1, "BGC -20C Freezer F1 / Box 1", 1),
    (4, "TIP200-3390", "+365 day", 40, "BGC Bench 2 / Cabinet C", 0),
    (5, "ETOH70-1180", "+180 day", 10, "Flammables Cabinet / Shelf 1", 0),
]


def _add_user(conn, username, full_name, role, password):
    salt, digest, iterations = auth.hash_password(password)
    cur = conn.execute(
        """INSERT INTO app_user
               (username, full_name, role, password_hash, password_salt, iterations)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (username, full_name, role, digest, salt, iterations),
    )
    return cur.lastrowid


def seed():
    conn = db.get_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]:
            return
        if demo_login_enabled():
            admin_id = _add_user(conn, *_USERS[0], DEMO_PASSWORDS["admin"])
            for row in _USERS[1:]:
                _add_user(conn, *row, DEMO_PASSWORDS[row[0]])
        else:
            password = os.environ.get("ADMIN_PASSWORD")
            if not password:
                raise RuntimeError("ADMIN_PASSWORD must be set when DEMO_LOGIN=0")
            admin_id = _add_user(conn, "admin", "Administrator", "admin", password)

        conn.executemany(
            "INSERT INTO app_setting (key, value) VALUES (?, ?)",
            [("boc_buffer_days", "7"), ("chase_hours", "48")],
        )

        item_ids = []
        for name, cat, unit, qty, burn, safety, lead, cost in _ITEMS:
            item_ids.append(conn.execute(
                """INSERT INTO item (name, category, unit, quantity_on_hand,
                                     daily_burn_rate, safety_stock, lead_time_days,
                                     unit_cost_php)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, cat, unit, qty, burn, safety, lead, cost),
            ).lastrowid)

        quote_ids = []
        for (idx, supplier, stype, price, cur, fx, moq, ship, cold, duty,
             lead, buffer, status) in _QUOTES:
            quote_ids.append(conn.execute(
                """INSERT INTO quote (item_id, supplier_name, supplier_type,
                                      unit_price, currency, fx_rate, moq,
                                      shipping_php, cold_chain_php, duty_rate,
                                      lead_time_days, boc_buffer_days, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_ids[idx], supplier, stype, price, cur, fx, moq, ship, cold,
                 duty, lead, buffer, status),
            ).lastrowid)

        for idx, lot_number, offset, qty, location, cold in _LOTS:
            conn.execute(
                """INSERT INTO lot (item_id, lot_number, expiry_date, quantity,
                                    location, cold_chain_ok)
                   VALUES (?, ?, date('now', '+8 hours', ?), ?, ?, ?)""",
                (item_ids[idx], lot_number, offset, qty, location, cold),
            )

        # One import shipment sitting in BOC filing, three days since the last
        # follow-up, so the 48-hour watchdog is red on first boot.
        (idx, supplier, stype, price, cur, fx, moq, ship, cold, duty,
         lead, buffer, _status) = _QUOTES[2]
        cost = landed.landed_cost(price, cur, fx, moq, ship, cold, duty)
        conn.execute(
            """INSERT INTO purchase_order
                   (quote_id, item_id, supplier_name, is_import, quantity,
                    landed_cost_php, status, permit_type, permit_ok,
                    doc_invoice, doc_packing, doc_awb, doc_coa_msds,
                    last_followup_at, created_by)
               VALUES (?, ?, ?, 1, ?, ?, 'at_boc_filing', 'FDA', 0, 1, 1, 1, 0,
                       datetime('now', '-3 day'), ?)""",
            (quote_ids[2], item_ids[idx], supplier, moq, cost, admin_id),
        )

        audit.record(conn, {"id": admin_id, "username": "admin"},
                     "seed.demo", "app", None, "BGC neuro-lab demo data")
        conn.commit()
    finally:
        conn.close()
