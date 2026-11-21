"""PBKDF2 passwords, opaque DB-backed sessions, and role gates.

Role checks live here and only here. Express them in routes as
Depends(auth.require_role(...)) -- never a second copy in the frontend that can
drift; the SPA reads the role from /api/me and only hides buttons.
"""
import hashlib
import hmac
import secrets

from fastapi import HTTPException, Request

from app import db

ITERATIONS = 210_000
SESSION_COOKIE = "exin_session"
CSRF_COOKIE = "exin_csrf"
SESSION_DAYS = 1

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2}

FAIL_WINDOW_SEC = 600
USER_FAIL_LIMIT = 8
IP_FAIL_LIMIT = 30


def hash_password(password: str):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS)
    return salt, digest.hex(), ITERATIONS


def verify_password(password: str, salt: str, expected: str, iterations: int) -> bool:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), expected)


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    conn.execute(
        """INSERT INTO session (token, user_id, created_at, expires_at)
           VALUES (?, ?, datetime('now'), datetime('now', ?))""",
        (token, user_id, f"+{SESSION_DAYS} day"),
    )
    return token


def user_for_token(conn, token):
    if not token:
        return None
    row = conn.execute(
        """SELECT u.id, u.username, u.full_name, u.role
             FROM session s JOIN app_user u ON u.id = s.user_id
            WHERE s.token = ? AND s.expires_at > datetime('now')
              AND u.is_active = 1""",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def current_user(request: Request):
    conn = db.get_conn()
    try:
        return user_for_token(conn, request.cookies.get(SESSION_COOKIE))
    finally:
        conn.close()


def require_role(minimum: str):
    need = ROLE_RANK[minimum]

    def dependency(request: Request):
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="authentication required")
        if ROLE_RANK[user["role"]] < need:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return dependency


# --------------------------------------------------------------------------- #
# Login throttling: counted before hashing, so a blocked attempt costs no CPU.
# --------------------------------------------------------------------------- #
def _prune(conn):
    conn.execute(
        "DELETE FROM login_throttle WHERE failed_at < datetime('now', ?)",
        (f"-{FAIL_WINDOW_SEC} seconds",),
    )


def throttle_blocked(conn, username: str, ip: str) -> bool:
    _prune(conn)
    user_hits = conn.execute(
        """SELECT COUNT(*) FROM login_throttle
            WHERE kind = 'user' AND key = ? AND failed_at >= datetime('now', ?)""",
        (username, f"-{FAIL_WINDOW_SEC} seconds"),
    ).fetchone()[0]
    ip_hits = conn.execute(
        """SELECT COUNT(*) FROM login_throttle
            WHERE kind = 'ip' AND key = ? AND failed_at >= datetime('now', ?)""",
        (ip, f"-{FAIL_WINDOW_SEC} seconds"),
    ).fetchone()[0]
    return user_hits >= USER_FAIL_LIMIT or ip_hits >= IP_FAIL_LIMIT


def record_failure(conn, username: str, ip: str):
    conn.execute(
        "INSERT INTO login_throttle (kind, key, failed_at) VALUES ('user', ?, datetime('now'))",
        (username,),
    )
    conn.execute(
        "INSERT INTO login_throttle (kind, key, failed_at) VALUES ('ip', ?, datetime('now'))",
        (ip,),
    )


def clear_user_failures(conn, username: str):
    conn.execute(
        "DELETE FROM login_throttle WHERE kind = 'user' AND key = ?", (username,)
    )
