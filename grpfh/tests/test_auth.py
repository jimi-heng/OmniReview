from __future__ import annotations

import hashlib

from grpfh.database import connect


def test_health_check(client):
    resp = client.get("/api/test")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True


def test_register_success(client, settings):
    resp = client.post("/api/register", json={"email": "new@example.com", "password": "abcdef"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT email FROM users WHERE email = ?", ("new@example.com",)).fetchone()
        assert row is not None


def test_register_duplicate(client, seeded_db):
    resp = client.post("/api/register", json={"email": "user@example.com", "password": "abcdef"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False


def test_register_short_password(client):
    resp = client.post("/api/register", json={"email": "x@example.com", "password": "123"})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_register_missing_fields(client):
    resp = client.post("/api/register", json={"email": "x@example.com"})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_login_success(client, seeded_db):
    resp = client.post("/api/login", json={"email": "user@example.com", "password": "password123"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["user_id"] == seeded_db.user_id


def test_login_wrong_password(client, seeded_db):
    resp = client.post("/api/login", json={"email": "user@example.com", "password": "wrong"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False


def test_login_nonexistent(client):
    resp = client.post("/api/login", json={"email": "nope@example.com", "password": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_login_md5_upgrade(client, seeded_db, settings):
    # Seeded legacy user uses MD5("legacy123") and should be upgraded transparently to werkzeug hash.
    resp = client.post("/api/login", json={"email": "legacy@example.com", "password": "legacy123"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT password FROM users WHERE email = ?", ("legacy@example.com",)).fetchone()
        assert row is not None
        stored = str(row["password"])
        # Not raw MD5 anymore.
        assert stored != hashlib.md5("legacy123".encode()).hexdigest()
        assert len(stored) > 32


def test_change_password_success(client, seeded_db):
    resp = client.post(
        "/api/change-password",
        json={
            "user_id": seeded_db.user_id,
            "current_password": "password123",
            "new_password": "newpass123",
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    # New login works, old fails.
    assert client.post("/api/login", json={"email": "user@example.com", "password": "password123"}).get_json()[
        "success"
    ] is False
    assert client.post("/api/login", json={"email": "user@example.com", "password": "newpass123"}).get_json()[
        "success"
    ] is True


def test_change_password_wrong_current(client, seeded_db):
    resp = client.post(
        "/api/change-password",
        json={
            "user_id": seeded_db.user_id,
            "current_password": "wrong",
            "new_password": "newpass123",
        },
    )
    assert resp.status_code == 401
    assert resp.get_json()["success"] is False

