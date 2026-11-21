"""Shared fixtures: every test gets a fresh seeded database in a temp file.

Each role fixture builds its own TestClient, because cookies live on the client:
sharing one client would let a later login overwrite an earlier session.
"""
import pytest
from fastapi.testclient import TestClient

import app.db as appdb

PASSWORDS = {
    "admin": "exin-demo-2026",
    "member": "exin-member-2026",
    "viewer": "exin-viewer-2026",
}


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(appdb, "DB_PATH", path)
    appdb.init_db(seed_demo=True)
    return path


@pytest.fixture
def client(db_path):
    from app.server import app

    with TestClient(app) as test_client:
        yield test_client


def login(client, role="admin"):
    response = client.post(
        "/api/login", json={"username": role, "password": PASSWORDS[role]}
    )
    assert response.status_code == 200, response.text
    # Double-submit CSRF: the header must mirror the readable cookie.
    client.headers["X-CSRF-Token"] = client.cookies["exin_csrf"]
    return response.json()


def _role_client(role):
    from app.server import app

    test_client = TestClient(app)
    login(test_client, role)
    return test_client


@pytest.fixture
def admin(db_path):
    c = _role_client("admin")
    yield c
    c.close()


@pytest.fixture
def member(db_path):
    c = _role_client("member")
    yield c
    c.close()


@pytest.fixture
def viewer(db_path):
    c = _role_client("viewer")
    yield c
    c.close()


@pytest.fixture
def db(db_path):
    conn = appdb.get_conn()
    yield conn
    conn.close()


def item_named(client, name):
    items = client.get("/api/items").json()
    return next(i for i in items if i["name"] == name)
