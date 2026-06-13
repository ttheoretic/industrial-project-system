"""Tests für Authentifizierung, Sitzungen und Rollenrechte (ohne API-Key)."""

import pytest
from fastapi.testclient import TestClient

from app import auth, config, database


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "auth.db"))
    database.init_db()
    yield


def test_password_hash_roundtrip():
    h = auth.hash_password("geheim123")
    assert h.startswith("pbkdf2_sha256$")
    assert auth.verify_password("geheim123", h)
    assert not auth.verify_password("falsch", h)


def test_login_and_session():
    auth.create_user("a@x.de", "Admin", "geheim123", role="admin")
    assert auth.login("a@x.de", "falsch") is None
    token = auth.login("a@x.de", "geheim123")
    assert token
    user = auth.user_for_token(token)
    assert user["email"] == "a@x.de" and user["role"] == "admin"
    assert "password_hash" not in user
    auth.logout(token)
    assert auth.user_for_token(token) is None


def test_inactive_user_cannot_login():
    u = auth.create_user("b@x.de", "B", "geheim123", role="viewer")
    auth.update_user(u["id"], active=False)
    assert auth.login("b@x.de", "geheim123") is None


def test_authorize_matrix():
    # admin darf alles
    assert auth.authorize("admin", "POST", "/api/users")
    assert auth.authorize("admin", "PUT", "/api/settings")
    # viewer darf nur lesen
    assert auth.authorize("viewer", "GET", "/api/offers")
    assert not auth.authorize("viewer", "POST", "/api/offers")
    # users-Verwaltung nur admin (auch lesen)
    assert not auth.authorize("vertrieb", "GET", "/api/users")
    # settings/preise nur admin schreiben, lesen für alle
    assert auth.authorize("vertrieb", "GET", "/api/settings")
    assert not auth.authorize("vertrieb", "PUT", "/api/settings")
    assert not auth.authorize("fertigung", "POST", "/api/material-prices")
    # vertrieb darf angebote schreiben, fertigung nicht
    assert auth.authorize("vertrieb", "POST", "/api/inquiries")
    assert not auth.authorize("fertigung", "POST", "/api/inquiries")
    assert not auth.authorize("fertigung", "POST", "/api/offers/1/pipeline")
    # fertigung darf projekte/zeit schreiben
    assert auth.authorize("fertigung", "POST", "/api/projects/1/time")
    assert auth.authorize("vertrieb", "POST", "/api/companies")


def test_http_flow_bootstrap_login_rbac():
    client = TestClient(app_for_test())
    # ohne Login: 401
    assert client.get("/api/offers").status_code == 401
    # Status zeigt: noch keine Benutzer
    assert client.get("/api/auth/status").json()["users_exist"] is False
    # ersten Admin anlegen → eingeloggt (Cookie gesetzt)
    r = client.post("/api/auth/bootstrap",
                    json={"name": "Chef", "email": "chef@x.de", "password": "geheim123"})
    assert r.status_code == 200
    assert client.get("/api/offers").status_code == 200  # jetzt erlaubt
    # zweiter Bootstrap nicht mehr möglich
    assert client.post("/api/auth/bootstrap",
                       json={"name": "X", "email": "y@x.de", "password": "geheim123"}).status_code == 409
    # Admin legt einen Viewer an
    client.post("/api/users", json={"name": "Leser", "email": "l@x.de",
                                     "password": "geheim123", "role": "viewer"})
    # Als Viewer einloggen (neuer Client) und Schreibversuch → 403
    viewer = TestClient(app_for_test())
    viewer.post("/api/auth/login", json={"email": "l@x.de", "password": "geheim123"})
    assert viewer.get("/api/offers").status_code == 200
    assert viewer.get("/api/users").status_code == 403       # nur Admin
    assert viewer.post("/api/companies", json={"name": "Test"}).status_code == 403


def test_last_admin_protected():
    client = TestClient(app_for_test())
    client.post("/api/auth/bootstrap",
                json={"name": "Chef", "email": "chef@x.de", "password": "geheim123"})
    me = client.get("/api/auth/status").json()["user"]
    # letzten Admin nicht degradieren
    r = client.put(f"/api/users/{me['id']}", json={"role": "viewer"})
    assert r.status_code == 409


def app_for_test():
    # Import erst hier, damit die monkeypatchte DB greift
    from app.main import app
    return app
