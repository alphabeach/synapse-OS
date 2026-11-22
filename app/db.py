"""SQLite connection, fresh-DB bootstrap, and transactional migrations."""
import os
import pathlib
import sqlite3

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "bgc_lab.db"))
SCHEMA_PATH = BASE_DIR / "schema.sql"

# schema.sql builds a fresh database complete, so a new file is stamped at this
# version and skips every migration step.
SCHEMA_VERSION = 2

# Append (version, sql) steps here for an EXISTING database. Never edit or
# renumber a released step. Each step is applied with its own version stamp in
# one transaction.
_MIGRATIONS = [
    # v2: purchase_order.quote_id loses its blanket UNIQUE so a cancelled PO
    # frees the quote for re-award. SQLite cannot drop an inline constraint, so
    # the table is rebuilt; cancelled POs keep sharing a quote.
    (2, """
        CREATE TABLE purchase_order_new (
            id              INTEGER PRIMARY KEY,
            quote_id        INTEGER NOT NULL REFERENCES quote(id),
            item_id         INTEGER NOT NULL REFERENCES item(id),
            supplier_name   TEXT    NOT NULL,
            is_import       INTEGER NOT NULL DEFAULT 1 CHECK (is_import IN (0, 1)),
            quantity        INTEGER NOT NULL CHECK (quantity > 0),
            landed_cost_php REAL    NOT NULL CHECK (landed_cost_php >= 0),
            status          TEXT    NOT NULL DEFAULT 'po_placed'
                            CHECK (status IN ('po_placed', 'shipped_awb', 'pre_arrival_docs',
                                              'at_boc_filing', 'permit_clearance', 'duties_assessed',
                                              'released_in_transit', 'received', 'discrepancy_hold',
                                              'cancelled')),
            permit_type     TEXT    NOT NULL DEFAULT 'NONE'
                            CHECK (permit_type IN ('NONE', 'FDA', 'PDEA', 'DENR')),
            permit_ok       INTEGER NOT NULL DEFAULT 0 CHECK (permit_ok IN (0, 1)),
            doc_invoice     INTEGER NOT NULL DEFAULT 0 CHECK (doc_invoice IN (0, 1)),
            doc_packing     INTEGER NOT NULL DEFAULT 0 CHECK (doc_packing IN (0, 1)),
            doc_awb         INTEGER NOT NULL DEFAULT 0 CHECK (doc_awb IN (0, 1)),
            doc_coa_msds    INTEGER NOT NULL DEFAULT 0 CHECK (doc_coa_msds IN (0, 1)),
            cold_chain_ok   INTEGER NOT NULL DEFAULT 1 CHECK (cold_chain_ok IN (0, 1)),
            last_followup_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
            discrepancy     TEXT    CHECK (discrepancy IN ('short_shipped',
                                                           'damaged_cold_chain', 'wrong_spec')),
            created_by      INTEGER REFERENCES app_user(id),
            created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),
            received_at     TIMESTAMP
        );
        INSERT INTO purchase_order_new SELECT * FROM purchase_order;
        DROP TABLE purchase_order;
        ALTER TABLE purchase_order_new RENAME TO purchase_order;
        CREATE INDEX idx_po_status ON purchase_order(status, last_followup_at);
        CREATE INDEX idx_po_item ON purchase_order(item_id);
        CREATE UNIQUE INDEX idx_po_one_per_quote
            ON purchase_order(quote_id) WHERE status != 'cancelled';
    """),
]


def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _has_schema():
    """A file on disk is not a database: an empty or truncated file must be
    rebuilt, not treated as an up-to-date one."""
    if not pathlib.Path(DB_PATH).exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_user'"
        ).fetchone() is not None
    finally:
        conn.close()


def init_db(seed_demo=True):
    """Create the database if absent or empty, else bring it to SCHEMA_VERSION."""
    if not _has_schema():
        conn = get_conn()
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()
        if seed_demo:
            from app import seed
            seed.seed()
        return
    _migrate()


def _migrate():
    conn = get_conn()
    try:
        # A table rebuild cannot run with foreign keys enforced: child rows
        # would block DROP TABLE. SQLite's documented recipe disables them for
        # the rebuild; this connection is closed straight after.
        conn.execute("PRAGMA foreign_keys = OFF")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version, sql in _MIGRATIONS:
            if version <= current:
                continue
            # executescript() commits any pending transaction first, so the
            # BEGIN/COMMIT live inside the script. A failing statement leaves the
            # transaction open and the version unstamped.
            try:
                conn.executescript(
                    f"BEGIN;\n{sql}\nPRAGMA user_version = {version};\nCOMMIT;"
                )
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.close()
