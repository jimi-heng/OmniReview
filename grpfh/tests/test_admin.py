from __future__ import annotations


def test_stats_empty_db(client):
    resp = client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["all"]["users"] == 0
    assert data["data"]["all"]["projects"]["total_proj"] == 0
    assert data["data"]["all"]["papers"] == 0


def test_stats_with_data(client, seeded_db):
    resp = client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["data"]["all"]["users"] >= 1
    assert data["data"]["all"]["projects"]["total_proj"] >= 1


def test_stats_time_buckets(client, seeded_db):
    resp = client.get("/api/admin/stats")
    d = resp.get_json()["data"]
    assert d["today"]["users"] == d["all"]["users"]
    assert d["today"]["projects"]["total_proj"] == d["all"]["projects"]["total_proj"]

