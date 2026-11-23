"""Auth, role gates, CSRF, session invalidation, and the demo login path."""
from fastapi.testclient import TestClient

from tests.conftest import PASSWORDS, USERNAMES, login


def test_unauthenticated_request_is_401(client):
    assert client.get("/api/dashboard").status_code == 401


def test_roles_are_enforced_by_route_dependencies(viewer, member):
    # viewer may read, may not create items (admin) or consume (member)
    assert viewer.get("/api/items").status_code == 200
    assert viewer.post("/api/items", json={"name": "X"}).status_code == 403
    assert viewer.post("/api/items/5/consume", json={"quantity": 1}).status_code == 403


def test_member_can_create_quote(member):
    items = member.get("/api/items").json()
    response = member.post("/api/quotes", json={
        "item_id": items[0]["id"],
        "supplier_name": "Test Supplier",
        "supplier_type": "local_ph",
        "unit_price": 1000,
    })
    assert response.status_code == 200, response.text
    assert response.json()["landed_cost_php"] > 0


def test_csrf_header_required(member):
    member.headers.pop("X-CSRF-Token")
    response = member.post("/api/items/5/consume", json={"quantity": 1})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


def test_csrf_header_present_succeeds(member):
    response = member.post("/api/items/5/consume", json={"quantity": 1})
    assert response.status_code == 200, response.text


def test_password_change_invalidates_other_sessions(client):
    login(client, "admin")
    from app.server import app
    other = TestClient(app)
    assert other.post("/api/login", json={
        "username": USERNAMES["admin"], "password": PASSWORDS["admin"],
    }).status_code == 200
    assert other.get("/api/me").status_code == 200

    response = client.post("/api/me/password", json={
        "current_password": PASSWORDS["admin"],
        "new_password": "a-brand-new-password",
    })
    assert response.status_code == 200, response.text

    # The other browser session is gone; the caller keeps a fresh one.
    assert other.get("/api/me").status_code == 401
    assert client.get("/api/me").status_code == 200


def test_demo_login_goes_through_real_auth(client):
    response = client.post("/api/demo-login")
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"
    assert client.get("/api/me").status_code == 200
    assert client.cookies["synapse_session"]


def test_login_throttling_returns_429(client):
    from app.auth import USER_FAIL_LIMIT

    payload = {"username": "admin", "password": "wrong"}
    for _ in range(USER_FAIL_LIMIT):
        assert client.post("/api/login", json=payload).status_code == 401
    assert client.post("/api/login", json=payload).status_code == 429


def test_demo_login_is_disabled_without_the_flag(client, monkeypatch):
    monkeypatch.setenv("DEMO_LOGIN", "0")
    assert client.post("/api/demo-login").status_code == 404


def test_seed_with_demo_login_off_uses_admin_password(tmp_path, monkeypatch):
    import app.db as appdb
    from app import auth as appauth

    monkeypatch.setenv("DEMO_LOGIN", "0")
    monkeypatch.setenv("ADMIN_PASSWORD", "a-real-admin-password")
    monkeypatch.setattr(appdb, "DB_PATH", str(tmp_path / "prod.db"))
    appdb.init_db(seed_demo=True)

    conn = appdb.get_conn()
    try:
        users = conn.execute(
            "SELECT username, password_hash, password_salt, iterations FROM app_user"
        ).fetchall()
    finally:
        conn.close()
    assert [u["username"] for u in users] == ["admin@lab.local"]
    assert appauth.verify_password(
        "a-real-admin-password",
        users[0]["password_salt"], users[0]["password_hash"], users[0]["iterations"],
    )


def test_db_path_honours_env(tmp_path, monkeypatch):
    import importlib

    import app.db as appdb

    target = str(tmp_path / "env.db")
    with monkeypatch.context() as m:
        m.setenv("DB_PATH", target)
        assert importlib.reload(appdb).DB_PATH == target
    importlib.reload(appdb)  # restore the default for later tests


def test_logout_ends_the_session(admin):
    admin.headers["X-CSRF-Token"] = admin.cookies["synapse_csrf"]
    assert admin.post("/api/logout").status_code == 200
    assert admin.get("/api/me").status_code == 401
