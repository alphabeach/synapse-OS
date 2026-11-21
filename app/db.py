"""SQLite connection, fresh-DB bootstrap, and transactional migrations."""
import pathlib
import sqlite3

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = str(BASE_DIR / "bgc_lab.db")
SCHEMA_PATH = BASE_DIR / "schema.sql"

# schema.sql builds a fresh database complete, so a new file is stamped at this
# version and skips every migration step.
SCHEMA_VERSION = 1

# Append (version, sql) steps here for an EXISTING database. Never edit or
# renumber a released step. Each step is applied with its own version stamp in
# one transaction.
_MIGRATIONS = []


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
