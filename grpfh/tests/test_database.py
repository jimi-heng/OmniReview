from __future__ import annotations

import time
from pathlib import Path

from grpfh.database import connect, ensure_schema


def test_connect_creates_parent_dirs(tmp_path: Path):
    db_path = tmp_path / "a" / "b" / "test.db"
    assert not db_path.parent.exists()
    conn = connect(db_path)
    try:
        assert db_path.parent.exists()
    finally:
        conn.close()


def test_connect_enables_foreign_keys(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        val = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert int(val) == 1
    finally:
        conn.close()


def test_connect_row_factory(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO t (name) VALUES ('x')")
        row = conn.execute("SELECT id, name FROM t LIMIT 1").fetchone()
        assert row["name"] == "x"
    finally:
        conn.close()


def test_ensure_schema_creates_all_tables(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"users", "projects", "literatures", "project_data"}.issubset(tables)
    finally:
        conn.close()


def test_ensure_schema_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        ensure_schema(conn)
    finally:
        conn.close()


def test_migration_columns_exist(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(literatures)").fetchall()}
        for c in [
            "doi",
            "abstract",
            "pdf_status",
            "pdf_path",
            "full_text_decision",
            "full_text_user_decision",
            "pico_evidence",
        ]:
            assert c in cols
    finally:
        conn.close()


def test_cascade_delete_project(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        cur.execute("INSERT INTO literatures (project_id, title) VALUES (?, 't')", (proj_id,))
        cur.execute(
            "INSERT INTO project_data (project_id, data_type, data_content) VALUES (?, 'pico', '{}')",
            (proj_id,),
        )
        conn.commit()

        cur.execute("DELETE FROM projects WHERE id = ?", (proj_id,))
        conn.commit()

        assert conn.execute("SELECT COUNT(*) FROM literatures WHERE project_id = ?", (proj_id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM project_data WHERE project_id = ?", (proj_id,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_update_trigger_projects(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        conn.commit()
        before = conn.execute("SELECT updated_at FROM projects WHERE id = ?", (proj_id,)).fetchone()["updated_at"]
        time.sleep(1.05)
        cur.execute("UPDATE projects SET project_name = 'p2' WHERE id = ?", (proj_id,))
        conn.commit()
        after = conn.execute("SELECT updated_at FROM projects WHERE id = ?", (proj_id,)).fetchone()["updated_at"]
        assert str(after) != str(before)
    finally:
        conn.close()


def test_update_trigger_project_data(tmp_path: Path):
    conn = connect(tmp_path / "test.db")
    try:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        cur.execute(
            "INSERT INTO project_data (project_id, data_type, data_content) VALUES (?, 'pico', '{}')",
            (proj_id,),
        )
        conn.commit()
        before = conn.execute(
            "SELECT updated_at FROM project_data WHERE project_id = ? AND data_type='pico'",
            (proj_id,),
        ).fetchone()["updated_at"]
        time.sleep(1.05)
        cur.execute(
            "UPDATE project_data SET data_content='{\"p\":\"x\"}' WHERE project_id = ? AND data_type='pico'",
            (proj_id,),
        )
        conn.commit()
        after = conn.execute(
            "SELECT updated_at FROM project_data WHERE project_id = ? AND data_type='pico'",
            (proj_id,),
        ).fetchone()["updated_at"]
        assert str(after) != str(before)
    finally:
        conn.close()

