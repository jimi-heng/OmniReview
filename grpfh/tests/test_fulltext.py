from __future__ import annotations

from io import BytesIO
from pathlib import Path

from grpfh.database import connect


def test_fetch_pdfs_no_doi(client, seeded_db, settings, mock_screening_modules):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO literatures (project_id, title, doi, ai_decision, user_decision, pdf_status)
            VALUES (?, 'No DOI', '', 'Included', 'Keep', 'Pending')
            """,
            (seeded_db.project_id,),
        )
        lit_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()

    resp = client.post("/api/fetch-pdfs", json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT pdf_status FROM literatures WHERE id = ?", (lit_id,)).fetchone()
        assert row["pdf_status"] == "Failed (No DOI)"


def test_fetch_pdfs_download_fail(client, seeded_db, settings, mock_screening_modules):
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO literatures (project_id, title, doi, ai_decision, user_decision, pdf_status)
            VALUES (?, 'Paywalled', '10.1/pay', 'Included', 'Keep', 'Pending')
            """,
            (seeded_db.project_id,),
        )
        lit_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()

    resp = client.post("/api/fetch-pdfs", json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id})
    assert resp.status_code == 200

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT pdf_status FROM literatures WHERE id = ?", (lit_id,)).fetchone()
        assert row["pdf_status"] == "Failed (Paywalled/Error)"


def test_upload_pdf_success(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO literatures (project_id, title, doi, pdf_status) VALUES (?, 't', '10.1/x', 'Pending')",
            (seeded_db.project_id,),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    pdf_bytes = b"%PDF-1.4\n%test\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
    data = {
        "paper_id": str(lit_id),
        "user_id": str(seeded_db.user_id),
        "file": (BytesIO(pdf_bytes), "x.pdf"),
    }
    resp = client.post("/api/upload-pdf", data=data, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute("SELECT pdf_status, pdf_path FROM literatures WHERE id = ?", (lit_id,)).fetchone()
        assert row["pdf_status"] == "Downloaded"
        assert row["pdf_path"]
        assert Path(str(row["pdf_path"])).exists()


def test_upload_pdf_no_file(client, seeded_db):
    resp = client.post(
        "/api/upload-pdf",
        data={"paper_id": "1", "user_id": str(seeded_db.user_id)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_run_fulltext_no_pending(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        conn.execute(
            "UPDATE literatures SET pdf_status='Pending' WHERE project_id = ?",
            (seeded_db.project_id,),
        )
        conn.commit()
    resp = client.post("/api/run-fulltext-ai", json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id})
    assert resp.status_code == 200
    assert resp.get_json()["count"] == 0


def test_run_fulltext_success(client, seeded_db, settings, mock_screening_modules):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO literatures (project_id, title, doi, pdf_status, pdf_path, full_text_decision)
            VALUES (?, 'DL', '10.1/dl', 'Downloaded', ?, 'Pending')
            """,
            (seeded_db.project_id, ""),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    pdf_dir = settings.resources_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "x.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")

    with connect(settings.db_path) as conn:
        conn.execute("UPDATE literatures SET pdf_path=? WHERE id=?", (str(pdf_path), lit_id))
        conn.commit()

    mock_screening_modules.FullTextScreening.run_fulltext_ai_sync.return_value = [
        {"id": lit_id, "decision": "Included", "evidence": "ev", "hl_path": str(pdf_path)},
    ]

    resp = client.post("/api/run-fulltext-ai", json={"project_id": seeded_db.project_id, "user_id": seeded_db.user_id})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        row = conn.execute(
            "SELECT full_text_decision, pico_evidence FROM literatures WHERE id=?",
            (lit_id,),
        ).fetchone()
        assert row["full_text_decision"] == "Included"
        assert row["pico_evidence"] == "ev"


def test_view_pdf_success(client, seeded_db, settings):
    pdf_dir = settings.resources_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "view.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")

    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO literatures (project_id, title, pdf_status, pdf_path) VALUES (?, 't', 'Downloaded', ?)",
            (seeded_db.project_id, str(pdf_path)),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    resp = client.get(f"/api/view-pdf?literature_id={lit_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"


def test_view_pdf_not_found(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO literatures (project_id, title, pdf_status, pdf_path) VALUES (?, 't', 'Downloaded', ?)",
            (seeded_db.project_id, str(settings.resources_root / "missing.pdf")),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    resp = client.get(f"/api/view-pdf?literature_id={lit_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 404


def test_view_pdf_traversal(client, seeded_db, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO literatures (project_id, title, pdf_status, pdf_path) VALUES (?, 't', 'Downloaded', ?)",
            (seeded_db.project_id, "../../etc/passwd"),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    resp = client.get(f"/api/view-pdf?literature_id={lit_id}&user_id={seeded_db.user_id}")
    assert resp.status_code == 403


def test_ownership_checks(client, seeded_db, settings):
    pdf_dir = settings.resources_root / "users" / f"user_{seeded_db.user_id}" / "projects" / f"project_{seeded_db.project_id}" / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "own.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%test\n%%EOF\n")

    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO literatures (project_id, title, pdf_status, pdf_path) VALUES (?, 't', 'Downloaded', ?)",
            (seeded_db.project_id, str(pdf_path)),
        )
        lit_id = int(cur.lastrowid)
        conn.commit()

    resp = client.get(f"/api/view-pdf?literature_id={lit_id}&user_id={seeded_db.other_user_id}")
    assert resp.status_code == 403
