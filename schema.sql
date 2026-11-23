-- Synapse Lab Ops -- fresh database schema.
-- Every closed status/role set is CHECKed here. Operational records are never
-- hard-deleted (items and quotes carry status flags instead).
PRAGMA foreign_keys = ON;

CREATE TABLE app_user (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE,
    full_name     TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (role IN ('viewer', 'member', 'admin')),
    password_hash TEXT    NOT NULL,
    password_salt TEXT    NOT NULL,
    iterations    INTEGER NOT NULL CHECK (iterations > 0),
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    TIMESTAMP NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE session (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES app_user(id),
    created_at TIMESTAMP NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX idx_session_user ON session(user_id);

-- Login throttling lives in SQLite so it survives a restart and is shared by
-- every worker, unlike an in-process dict.
CREATE TABLE login_throttle (
    kind      TEXT NOT NULL CHECK (kind IN ('user', 'ip')),
    key       TEXT NOT NULL,
    failed_at TIMESTAMP NOT NULL
);
CREATE INDEX idx_throttle ON login_throttle(kind, key, failed_at);

CREATE TABLE app_setting (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE item (
    id               INTEGER PRIMARY KEY,
    name             TEXT    NOT NULL,
    category         TEXT    NOT NULL DEFAULT 'other'
                     CHECK (category IN ('antibody', 'reagent', 'media', 'chemical', 'consumable', 'other')),
    unit             TEXT    NOT NULL DEFAULT 'vial',
    quantity_on_hand INTEGER NOT NULL DEFAULT 0 CHECK (quantity_on_hand >= 0),
    daily_burn_rate  REAL    NOT NULL DEFAULT 0 CHECK (daily_burn_rate >= 0),
    safety_stock     INTEGER NOT NULL DEFAULT 0 CHECK (safety_stock >= 0),
    lead_time_days   INTEGER NOT NULL DEFAULT 0 CHECK (lead_time_days >= 0),
    unit_cost_php    REAL    NOT NULL DEFAULT 0 CHECK (unit_cost_php >= 0),
    status           TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated')),
    created_at       TIMESTAMP NOT NULL DEFAULT (datetime('now'))
);

-- One supplier quote for one item. landed cost is computed, never stored.
CREATE TABLE quote (
    id              INTEGER PRIMARY KEY,
    item_id         INTEGER NOT NULL REFERENCES item(id),
    supplier_name   TEXT    NOT NULL,
    supplier_type   TEXT    NOT NULL CHECK (supplier_type IN ('local_ph', 'alibaba', 'wechat', 'us_eu')),
    unit_price      REAL    NOT NULL CHECK (unit_price > 0),
    currency        TEXT    NOT NULL DEFAULT 'PHP' CHECK (currency IN ('PHP', 'USD')),
    fx_rate         REAL    NOT NULL DEFAULT 1 CHECK (fx_rate > 0),
    moq             INTEGER NOT NULL DEFAULT 1 CHECK (moq > 0),
    shipping_php    REAL    NOT NULL DEFAULT 0 CHECK (shipping_php >= 0),
    cold_chain_php  REAL    NOT NULL DEFAULT 0 CHECK (cold_chain_php >= 0),
    duty_rate       REAL    NOT NULL DEFAULT 0 CHECK (duty_rate >= 0),
    lead_time_days  INTEGER NOT NULL DEFAULT 0 CHECK (lead_time_days >= 0),
    boc_buffer_days INTEGER NOT NULL DEFAULT 0 CHECK (boc_buffer_days >= 0),
    status          TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'primary', 'backup', 'rejected')),
    note            TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now'))
);
-- One primary award per item, enforced by the database, not by a handler.
CREATE UNIQUE INDEX idx_quote_one_primary ON quote(item_id) WHERE status = 'primary';
CREATE INDEX idx_quote_item ON quote(item_id);

-- One awarded quote = one PO for one item (po_line is the upgrade path).
CREATE TABLE purchase_order (
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
    permit_type     TEXT    NOT NULL DEFAULT 'NONE' CHECK (permit_type IN ('NONE', 'FDA', 'PDEA', 'DENR')),
    permit_ok       INTEGER NOT NULL DEFAULT 0 CHECK (permit_ok IN (0, 1)),
    doc_invoice     INTEGER NOT NULL DEFAULT 0 CHECK (doc_invoice IN (0, 1)),
    doc_packing     INTEGER NOT NULL DEFAULT 0 CHECK (doc_packing IN (0, 1)),
    doc_awb         INTEGER NOT NULL DEFAULT 0 CHECK (doc_awb IN (0, 1)),
    doc_coa_msds    INTEGER NOT NULL DEFAULT 0 CHECK (doc_coa_msds IN (0, 1)),
    cold_chain_ok   INTEGER NOT NULL DEFAULT 1 CHECK (cold_chain_ok IN (0, 1)),
    last_followup_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    discrepancy     TEXT    CHECK (discrepancy IN ('short_shipped', 'damaged_cold_chain', 'wrong_spec')),
    created_by      INTEGER REFERENCES app_user(id),
    created_at      TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    received_at     TIMESTAMP
);
CREATE INDEX idx_po_status ON purchase_order(status, last_followup_at);
CREATE INDEX idx_po_item ON purchase_order(item_id);
-- One live PO per quote; a cancelled PO frees its quote for a re-award.
CREATE UNIQUE INDEX idx_po_one_per_quote
    ON purchase_order(quote_id) WHERE status != 'cancelled';

-- Lots are minted only on receipt; expiry is mandatory, so expiring stock is
-- always visible rather than silently missing an expiry date.
CREATE TABLE lot (
    id             INTEGER PRIMARY KEY,
    item_id        INTEGER NOT NULL REFERENCES item(id),
    po_id          INTEGER REFERENCES purchase_order(id),
    lot_number     TEXT    NOT NULL,
    expiry_date    DATE    NOT NULL,
    quantity       INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    location       TEXT    NOT NULL,
    cold_chain_ok  INTEGER NOT NULL DEFAULT 1 CHECK (cold_chain_ok IN (0, 1)),
    received_date  DATE    NOT NULL DEFAULT (date('now', '+8 hours')),
    created_at     TIMESTAMP NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_lot_item_expiry ON lot(item_id, expiry_date);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY,
    occurred_at TIMESTAMP NOT NULL DEFAULT (datetime('now', '+8 hours')),
    user_id     INTEGER,
    username    TEXT,
    action      TEXT    NOT NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    detail      TEXT
);
CREATE INDEX idx_audit_time ON audit_log(occurred_at);
