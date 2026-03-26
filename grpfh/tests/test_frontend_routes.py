from __future__ import annotations


def test_index_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert "AI Screening Tool" in resp.get_data(as_text=True)


def test_static_js(client):
    resp = client.get("/js/1-globals.js")
    assert resp.status_code == 200
    # Some environments set it as text/plain; basic smoke is enough here.
    assert resp.get_data(as_text=True)


def test_blocked_db_file(client):
    assert client.get("/ai_screening.db").status_code == 404


def test_blocked_env(client):
    assert client.get("/.env").status_code == 404


def test_blocked_pyproject(client):
    assert client.get("/pyproject.toml").status_code == 404


def test_disallowed_extension(client):
    assert client.get("/foo.py").status_code == 404


def test_path_traversal(client):
    assert client.get("/../../../etc/passwd").status_code == 404

