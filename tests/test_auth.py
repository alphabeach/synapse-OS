"""Auth, role gates, CSRF, session invalidation, and the demo login path."""
from fastapi.testclient import TestClient

from tests.conftest import PASSWORDS, login


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
        "username": "admin", "password": PASSWORDS["admin"],
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
    assert client.cookies["exin_session"]


def test_logout_ends_the_session(admin):
    admin.headers["X-CSRF-Token"] = admin.cookies["exin_csrf"]
    assert admin.post("/api/logout").status_code == 200
    assert admin.get("/api/me").status_code == 401
