from __future__ import annotations

from io import BytesIO

from grpfh.app import create_app
from grpfh.database import connect
from grpfh.settings import Settings


def test_path_traversal_view_pdf(client, seeded_db, settings):
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


def test_sql_injection_login(client):
    resp = client.post("/api/login", json={"email": "' OR 1=1 --", "password": "x"})
    assert resp.status_code == 400
    assert resp.get_json()["success"] is False


def test_auth_bypass_get_literatures(client, seeded_db):
    resp = client.post(
        "/api/get-literatures",
        json={"project_id": seeded_db.project_id, "user_id": seeded_db.other_user_id},
    )
    assert resp.status_code == 403


def test_large_file_upload_413(tmp_path):
    settings = Settings(
        host="127.0.0.1",
        port=3000,
        debug=True,
        db_path=tmp_path / "test.db",
        resources_root=tmp_path / "resources",
        outputs_root=tmp_path / "outputs",
        cors_origins="*",
        max_content_length_bytes=512,
    )
    app = create_app(settings)
    app.config.update(TESTING=True)
    client = app.test_client()

    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = int(cur.lastrowid)
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = int(cur.lastrowid)
        cur.execute("INSERT INTO literatures (project_id, title) VALUES (?, 't')", (proj_id,))
        lit_id = int(cur.lastrowid)
        conn.commit()

    big = b"x" * 2048
    data = {"paper_id": str(lit_id), "user_id": str(user_id), "file": (BytesIO(big), "big.pdf")}
    resp = client.post("/api/upload-pdf", data=data, content_type="multipart/form-data")
    assert resp.status_code == 413


def test_no_ownership_check_endpoints(client, seeded_db, settings):
    # Document current behavior: delete-project does not validate ownership.
    resp = client.post("/api/delete-project", json={"project_id": seeded_db.other_project_id})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True

    with connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects WHERE id = ?", (seeded_db.other_project_id,)).fetchone()[0] == 0

