"""Login, demo login, logout, /me, and password change.

Every role decision in the app goes through auth.require_role; the SPA reads the
role from /api/me and only hides buttons with it.
"""
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app import audit, auth, db

router = APIRouter()

# Seeded demo account. The button posts these through the normal login handler;
# nothing bypasses authentication.
DEMO_LOGIN = {"username": "admin", "password": "exin-demo-2026"}


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: str
    new_password: str


def _public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def _start_session(conn, response: Response, row):
    token = auth.create_session(conn, row["id"])
    csrf = secrets.token_urlsafe(24)
    secure = os.environ.get("COOKIE_SECURE") == "1"
    max_age = auth.SESSION_DAYS * 86400
    response.set_cookie(
        auth.SESSION_COOKIE, token, httponly=True, samesite="lax",
        secure=secure, max_age=max_age, path="/",
    )
    response.set_cookie(
        auth.CSRF_COOKIE, csrf, httponly=False, samesite="lax",
        secure=secure, max_age=max_age, path="/",
    )
    return _public(row)


def _do_login(body: LoginBody, request: Request, response: Response):
    username = body.username.strip().lower()
    ip = (request.client.host if request.client else None) or "unknown"
    conn = db.get_conn()
    try:
        if auth.throttle_blocked(conn, username, ip):
            raise HTTPException(
                status_code=429, detail="too many failed attempts; try again later"
            )
        row = conn.execute(
            """SELECT id, username, full_name, role, password_hash,
                      password_salt, iterations
                 FROM app_user WHERE username = ? AND is_active = 1""",
            (username,),
        ).fetchone()
        if row is None or not auth.verify_password(
            body.password, row["password_salt"], row["password_hash"], row["iterations"]
        ):
            auth.record_failure(conn, username, ip)
            conn.commit()
            raise HTTPException(status_code=401, detail="invalid username or password")
        auth.clear_user_failures(conn, username)
        audit.record(conn, row, "auth.login", "app_user", row["id"])
        result = _start_session(conn, response, row)
        conn.commit()
        return result
    finally:
        conn.close()


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    return _do_login(body, request, response)


@router.post("/demo-login")
def demo_login(request: Request, response: Response):
    return _do_login(LoginBody(**DEMO_LOGIN), request, response)


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        conn = db.get_conn()
        try:
            conn.execute("DELETE FROM session WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    response.delete_cookie(auth.CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(auth.require_role("viewer"))):
    return user


@router.post("/me/password")
def change_password(
    body: PasswordBody,
    response: Response,
    user: dict = Depends(auth.require_role("viewer")),
):
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=400, detail="new password must be at least 8 characters"
        )
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT password_hash, password_salt, iterations FROM app_user WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="user not found")
        if not auth.verify_password(
            body.current_password, row["password_salt"], row["password_hash"],
            row["iterations"],
        ):
            raise HTTPException(status_code=400, detail="current password is incorrect")
        salt, digest, iterations = auth.hash_password(body.new_password)
        conn.execute(
            """UPDATE app_user SET password_hash = ?, password_salt = ?,
                                  iterations = ? WHERE id = ?""",
            (digest, salt, iterations, user["id"]),
        )
        # A password change invalidates every existing session for that user.
        conn.execute("DELETE FROM session WHERE user_id = ?", (user["id"],))
        audit.record(conn, user, "user.password_change", "app_user", user["id"])
        # Keep the caller signed in with a fresh token.
        fresh = conn.execute(
            "SELECT id, username, full_name, role FROM app_user WHERE id = ?",
            (user["id"],),
        ).fetchone()
        result = _start_session(conn, response, fresh)
        conn.commit()
        return {"ok": True, "user": result}
    finally:
        conn.close()
