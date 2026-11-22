"""Migration integrity: a failed step must never stamp a false version."""
import sqlite3

import pytest

import app.db as appdb


def _meta(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _user_version(path):
    return _meta(path, "PRAGMA user_version")[0][0]


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    path = tmp_path / "migrate.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db(seed_demo=False)
    return path


def test_fresh_database_is_stamped(fresh):
    assert _user_version(str(fresh)) == appdb.SCHEMA_VERSION


def test_an_empty_file_is_rebuilt_not_trusted(tmp_path, monkeypatch):
    """A zero-byte file (crash, volume mount, deleted DB reopened) must boot."""
    path = tmp_path / "empty.db"
    path.write_bytes(b"")
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db(seed_demo=True)

    tables = {r[0] for r in _meta(
        str(path), "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "app_user" in tables
    assert _user_version(str(path)) == appdb.SCHEMA_VERSION


def test_failed_step_rolls_back_and_keeps_the_version(fresh, monkeypatch):
    monkeypatch.setattr(appdb, "_MIGRATIONS", [
        (appdb.SCHEMA_VERSION + 1,
         "CREATE TABLE half_done (id INTEGER PRIMARY KEY);\nCREATE TABLE broken ("),
    ])
    with pytest.raises(sqlite3.OperationalError):
        appdb.init_db()

    assert _user_version(str(fresh)) == appdb.SCHEMA_VERSION
    tables = {r[0] for r in _meta(
        str(fresh), "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "half_done" not in tables


def test_successful_step_applies_and_stamps(fresh, monkeypatch):
    monkeypatch.setattr(appdb, "_MIGRATIONS", [
        (appdb.SCHEMA_VERSION + 1, "CREATE TABLE extra (id INTEGER PRIMARY KEY);"),
    ])
    appdb.init_db()

    assert _user_version(str(fresh)) == appdb.SCHEMA_VERSION + 1
    tables = {r[0] for r in _meta(
        str(fresh), "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    assert "extra" in tables


def test_v1_database_upgrades_to_partial_unique_po_index(tmp_path, monkeypatch):
    path = tmp_path / "v1.db"
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    monkeypatch.setattr(appdb, "SCHEMA_VERSION", 1)
    monkeypatch.setattr(appdb, "_MIGRATIONS", [])
    appdb.init_db(seed_demo=False)

    monkeypatch.undo()
    monkeypatch.setattr(appdb, "DB_PATH", str(path))
    appdb.init_db()

    assert _user_version(str(path)) == appdb.SCHEMA_VERSION
    indexes = {
        r[0] for r in _meta(
            str(path), "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    assert "idx_po_one_per_quote" in indexes

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("INSERT INTO item (name) VALUES ('x')")
        conn.execute(
            """INSERT INTO quote (item_id, supplier_name, supplier_type, unit_price)
               VALUES (1, 's', 'local_ph', 1)"""
        )
        insert = """INSERT INTO purchase_order
                        (quote_id, item_id, supplier_name, quantity,
                         landed_cost_php, status)
                    VALUES (1, 1, 's', 1, 1, ?)"""
        conn.execute(insert, ("cancelled",))
        conn.execute(insert, ("cancelled",))  # cancelled POs may share a quote
        conn.execute(insert, ("po_placed",))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert, ("po_placed",))  # live POs may not
    finally:
        conn.close()


def test_migration_is_idempotent(fresh, monkeypatch):
    monkeypatch.setattr(appdb, "_MIGRATIONS", [
        (appdb.SCHEMA_VERSION + 1, "CREATE TABLE extra (id INTEGER PRIMARY KEY);"),
    ])
    appdb.init_db()
    appdb.init_db()  # second boot must not re-run the step
    assert _user_version(str(fresh)) == appdb.SCHEMA_VERSION + 1
