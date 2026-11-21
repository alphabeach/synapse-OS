"""Append-only audit trail. Failure is logged loudly, never swallowed."""
import logging

log = logging.getLogger("exin.audit")


def record(conn, user, action, entity_type=None, entity_id=None, detail=None):
    """Stage one audit row in the caller's transaction.

    Best effort: an audit failure must not abort the operation it records, but
    it must be visible in the logs (unlike a silent except: pass).
    """
    # `user` is a dict from a route dependency or a sqlite3.Row from login.
    try:
        user_id, username = (user["id"], user["username"]) if user else (None, None)
    except (KeyError, IndexError, TypeError):
        user_id, username = None, None
    try:
        conn.execute(
            """INSERT INTO audit_log
                   (occurred_at, user_id, username, action, entity_type, entity_id, detail)
               VALUES (datetime('now'), ?, ?, ?, ?, ?, ?)""",
            (user_id, username, action, entity_type, entity_id, detail),
        )
    except Exception:
        log.exception("audit write failed: action=%s entity=%s/%s", action, entity_type, entity_id)
