from __future__ import annotations

import time

from grpfh.database import connect


def test_create_project(client, seeded_db):
    resp = client.post("/api/create-project", json={"user_id": seeded_db.user_id, "project_name": "P1"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["project_id"], int)


def test_get_projects_ordered(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'Old')", (seeded_db.user_id,))
        old_id = int(cur.lastrowid)
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'New')", (seeded_db.user_id,))
        conn.commit()

    # Make "Old" the most recently updated.
    time.sleep(1.05)
    assert client.post("/api/get-project-data", json={"project_id": old_id}).status_code == 200

    resp = client.post("/api/get-projects", json={"user_id": seeded_db.user_id})
    assert resp.status_code == 200
    projects = resp.get_json()["data"]
    assert len(projects) >= 2
    assert projects[0]["id"] == old_id


def test_get_projects_limit_5(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        for i in range(10):
            cur.execute(
                "INSERT INTO projects (user_id, project_name) VALUES (?, ?)",
                (seeded_db.user_id, f"P{i}"),
            )
        conn.commit()

    resp = client.post("/api/get-projects", json={"user_id": seeded_db.user_id})
    assert resp.status_code == 200
    projects = resp.get_json()["data"]
    assert len(projects) <= 5


def test_save_project_data_upsert(client, seeded_db):
    resp = client.post(
        "/api/save-project-data",
        json={"project_id": seeded_db.project_id, "data_type": "pico", "data_content": {"p": "X"}},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    resp = client.post(
        "/api/save-project-data",
        json={"project_id": seeded_db.project_id, "data_type": "pico", "data_content": {"p": "Y"}},
    )
    assert resp.status_code == 200

    resp = client.post("/api/get-project-data", json={"project_id": seeded_db.project_id, "data_type": "pico"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["p"] == "Y"


def test_get_project_data_by_type(client, seeded_db):
    resp = client.post("/api/get-project-data", json={"project_id": seeded_db.project_id, "data_type": "pico"})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert isinstance(data, dict)
    assert "p" in data


def test_get_project_data_all(client, seeded_db):
    resp = client.post("/api/get-project-data", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert "pico" in data
    assert "protocol" in data


def test_update_status(client, seeded_db, settings):
    resp = client.post(
        "/api/update-project-status",
        json={"project_id": seeded_db.project_id, "status": "Import/Search"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT status FROM projects WHERE id = ?", (seeded_db.project_id,)).fetchone()
        assert row["status"] == "Import/Search"


def test_update_name(client, seeded_db, settings):
    resp = client.post(
        "/api/update-project-name",
        json={"project_id": seeded_db.project_id, "project_name": "Renamed"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT project_name FROM projects WHERE id = ?", (seeded_db.project_id,)).fetchone()
        assert row["project_name"] == "Renamed"


def test_delete_project_cascade(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        conn.execute("INSERT INTO literatures (project_id, title) VALUES (?, 't')", (seeded_db.project_id,))
        conn.commit()

    resp = client.post("/api/delete-project", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects WHERE id = ?", (seeded_db.project_id,)).fetchone()[0] == 0
        assert (
            conn.execute("SELECT COUNT(*) FROM literatures WHERE project_id = ?", (seeded_db.project_id,)).fetchone()[0]
            == 0
        )


def test_missing_fields_400(client):
    assert client.post("/api/create-project", json={"user_id": 1}).status_code == 400
    assert client.post("/api/get-projects", json={}).status_code == 400
    assert client.post("/api/save-project-data", json={"project_id": 1}).status_code == 400

