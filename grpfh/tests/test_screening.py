from __future__ import annotations

import csv
import io

from grpfh.database import connect


def test_run_screening_success(client, seeded_db, mock_screening_modules, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO literatures (project_id, title, abstract, ai_decision, reasoning) VALUES (?, 'P', 'A', 'Pending', 'R')",
            (seeded_db.project_id,),
        )
        lit_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()

    mock_screening_modules.AbstractScreening.run_ai_screening_sync.return_value = [
        {"id": lit_id, "ai_decision": "Included", "reasoning": "ok"},
    ]

    resp = client.post("/api/run-ai-screening", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] == 1

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT ai_decision, reasoning FROM literatures WHERE id = ?", (lit_id,)).fetchone()
        assert row["ai_decision"] == "Included"
        assert row["reasoning"] == "ok"


def test_run_screening_no_pico(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            "DELETE FROM project_data WHERE project_id = ? AND data_type = 'pico'",
            (seeded_db.project_id,),
        )
        conn.commit()

    resp = client.post("/api/run-ai-screening", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_run_screening_no_pending(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE literatures SET ai_decision='Included' WHERE project_id = ?",
            (seeded_db.project_id,),
        )
        conn.commit()
    resp = client.post("/api/run-ai-screening", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["count"] == 0


def test_run_screening_error_result(client, seeded_db, mock_screening_modules, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO literatures (project_id, title, abstract, ai_decision, reasoning) VALUES (?, 'P', 'A', 'Pending', 'R')",
            (seeded_db.project_id,),
        )
        lit_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()

    mock_screening_modules.AbstractScreening.run_ai_screening_sync.return_value = [
        {"id": lit_id, "ai_decision": "", "reasoning": ""},
    ]

    resp = client.post("/api/run-ai-screening", json={"project_id": seeded_db.project_id})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT ai_decision FROM literatures WHERE id = ?", (lit_id,)).fetchone()
        assert row["ai_decision"] == "Error"


def test_export_csv_content(client, seeded_db):
    resp = client.get(f"/api/export-csv?project_id={seeded_db.project_id}")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("Content-type", "")
    text = resp.get_data(as_text=True)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][:3] == ["Database_ID", "Title", "Authors"]


def test_export_csv_decision_mapping(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO literatures (project_id, title, ai_decision, user_decision, reasoning)
            VALUES (?, 'Map', 'Excluded', 'Include', 'r')
            """,
            (seeded_db.project_id,),
        )
        conn.commit()

    resp = client.get(f"/api/export-csv?project_id={seeded_db.project_id}")
    text = resp.get_data(as_text=True)
    assert "Map" in text
    assert "Included" in text


def test_export_csv_content_disposition(client, seeded_db):
    resp = client.get(f"/api/export-csv?project_id={seeded_db.project_id}")
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "screening_results_" in cd

