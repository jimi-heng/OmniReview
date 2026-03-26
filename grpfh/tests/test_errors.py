from __future__ import annotations


def test_404_json(client):
    resp = client.get("/nope")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert isinstance(data.get("message"), str) and data["message"]


def test_405_json(client):
    # Use a known GET-only endpoint and call it with POST to ensure 405.
    resp = client.post("/api/test")
    assert resp.status_code == 405
    data = resp.get_json()
    assert data["success"] is False


def test_500_json(app, client):
    def boom():
        raise RuntimeError("boom")

    app.add_url_rule("/boom", "boom", boom, methods=["GET"])
    resp = client.get("/boom")
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
    assert data["message"] == "Internal server error"
