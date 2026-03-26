from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from grpfh.database import connect


def _create_pdf(settings, seed, name: str) -> Path:
    pdf_dir = (
        settings.resources_root
        / "users"
        / f"user_{seed.user_id}"
        / "projects"
        / f"project_{seed.project_id}"
        / "pdf"
    )
    pdf_dir.mkdir(parents=True, exist_ok=True)
    p = pdf_dir / name
    p.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")
    return p


@patch("grpfh.routes.api.extraction.subprocess.run")
def test_run_extraction_success(mock_run, client, seeded_db, settings):
    mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    pdf_path = _create_pdf(settings, seeded_db, "inc.pdf")
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO literatures (project_id, title, pdf_path, full_text_decision, full_text_user_decision)
            VALUES (?, 't', ?, 'Included', 'Keep')
            """,
            (seeded_db.project_id, str(pdf_path)),
        )
        conn.commit()

    resp = client.post(
        "/api/run-data-extraction",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id},
    )
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


@patch("grpfh.routes.api.extraction.subprocess.run")
def test_run_extraction_no_included(mock_run, client, seeded_db):
    mock_run.return_value = type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    resp = client.post(
        "/api/run-data-extraction",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id},
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


@patch("grpfh.routes.api.extraction.subprocess.run")
def test_run_extraction_script_crash(mock_run, client, seeded_db, settings):
    mock_run.return_value = type("P", (), {"returncode": 1, "stdout": "", "stderr": "err" * 200})()

    pdf_path = _create_pdf(settings, seeded_db, "inc2.pdf")
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO literatures (project_id, title, pdf_path, full_text_decision, full_text_user_decision)
            VALUES (?, 't', ?, 'Included', 'Keep')
            """,
            (seeded_db.project_id, str(pdf_path)),
        )
        conn.commit()

    resp = client.post(
        "/api/run-data-extraction",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "Script crashed!" in data["message"]


def test_download_xlsx(client, seeded_db, settings):
    out_dir = settings.outputs_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / f"proj_{seeded_db.project_id}_extracted.xlsx"
    xlsx_path.write_bytes(b"xlsx")

    resp = client.get(f"/api/download-extraction?project_id={seeded_db.project_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 200


def test_download_csv(client, seeded_db, settings):
    out_dir = settings.outputs_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"proj_{seeded_db.project_id}_extracted.csv"
    csv_path.write_text("a,b\n1,2\n", encoding="utf-8")

    resp = client.get(
        f"/api/download-extraction?project_id={seeded_db.project_id}&user_id={seeded_db.user_id}&type=csv"
    )
    assert resp.status_code == 200


def test_download_not_found(client, seeded_db):
    resp = client.get(f"/api/download-extraction?project_id={seeded_db.project_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 404


def test_preview_success(client, seeded_db, settings):
    out_dir = settings.outputs_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"proj_{seeded_db.project_id}_extracted.csv"
    csv_path.write_text("col1,col2\nx,y\n", encoding="utf-8")

    resp = client.get(f"/api/get-extraction-preview?project_id={seeded_db.project_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["columns"] == ["col1", "col2"]
    assert data["data"][0]["col1"] == "x"


def test_preview_not_extracted(client, seeded_db):
    resp = client.get(f"/api/get-extraction-preview?project_id={seeded_db.project_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False

