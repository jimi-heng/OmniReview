from __future__ import annotations

from grpfh.database import connect


def test_upload_success(client, seeded_db, settings):
    resp = client.post(
        "/api/upload-literature",
        json={
            "project_id": seeded_db.project_id,
            "title": "A paper",
            "author": "X",
            "journal": "J",
            "year": 2024,
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["inserted"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT title, ai_decision FROM literatures WHERE project_id = ? AND title = ?",
            (seeded_db.project_id, "A paper"),
        ).fetchone()
        assert row is not None
        assert row["ai_decision"] == "Pending"


def test_upload_duplicate_skipped(client, seeded_db):
    client.post("/api/upload-literature", json={"project_id": seeded_db.project_id, "title": "Dup"})
    resp = client.post("/api/upload-literature", json={"project_id": seeded_db.project_id, "title": "Dup"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["inserted"] is False


def test_get_literatures_success(client, seeded_db):
    resp = client.post(
        "/api/get-literatures",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert isinstance(data["data"], list)


def test_get_literatures_ownership(client, seeded_db):
    resp = client.post(
        "/api/get-literatures",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.other_user_id},
    )
    assert resp.status_code == 403
    assert resp.get_json()["success"] is False


def test_update_decision(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO literatures (project_id, title) VALUES (?, 't')", (seeded_db.project_id,))
        lit_id = int(cur.lastrowid)
        conn.commit()

    resp = client.post(
        "/api/update-literature-decision",
        json={"literature_id": lit_id, "user_decision": "Include", "reasoning": "r"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT user_decision, reasoning FROM literatures WHERE id = ?",
            (lit_id,),
        ).fetchone()
        assert row["user_decision"] == "Include"
        assert row["reasoning"] == "r"


def test_update_nothing(client, seeded_db):
    resp = client.post("/api/update-literature-decision", json={"literature_id": seeded_db.literature_ids[0]})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_search_pubmed_mock(client, seeded_db, mock_screening_modules, settings):
    mock_screening_modules.AbstractScreening.literature_search_all.return_value = [
        {"title": "T1", "author": "A", "journal": "J", "year": 2020, "doi": "10.1/x", "abstract": "abs"},
        {"title": "T2", "author": "B", "journal": "J2", "year": 2021, "doi": "", "abstract": ""},
    ]
    resp = client.post(
        "/api/search-pubmed",
        json={"project_id": seeded_db.project_id, "keywords": "k", "max_papers": 2, "databases": ["pubmed"]},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] == 2

    with connect(settings.db_path) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM literatures WHERE project_id = ? AND title IN ('T1','T2')",
            (seeded_db.project_id,),
        ).fetchone()[0] == 2


def test_search_pubmed_dedup(client, seeded_db, mock_screening_modules):
    mock_screening_modules.AbstractScreening.literature_search_all.return_value = [{"title": "T1"}]
    client.post("/api/upload-literature", json={"project_id": seeded_db.project_id, "title": "T1"})
    resp = client.post("/api/search-pubmed", json={"project_id": seeded_db.project_id, "keywords": "k"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] == 0


def test_search_pubmed_exception(client, seeded_db, mock_screening_modules):
    mock_screening_modules.AbstractScreening.literature_search_all.side_effect = RuntimeError("boom")
    resp = client.post("/api/search-pubmed", json={"project_id": seeded_db.project_id, "keywords": "k"})
    assert resp.status_code == 500
    assert resp.get_json()["success"] is False

