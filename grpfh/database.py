from __future__ import annotations

import os
from pathlib import Path
import sqlite3


def default_db_path() -> Path:
    # Prefer the repo-root DB (matches existing upgrade scripts in grpfh/).
    repo_root = Path(__file__).resolve().parents[1]
    return Path(os.getenv("GRPFH_DB_PATH", str(repo_root / "ai_screening.db"))).resolve()


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def _ensure_column(conn: sqlite3.Connection, table: str, col: str, ddl: str) -> None:
    if col in _table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create missing tables/columns (idempotent, safe to run at startup)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            status TEXT DEFAULT 'PICO Setup',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS literatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            journal TEXT DEFAULT '',
            year INTEGER,
            doi TEXT DEFAULT '',
            abstract TEXT DEFAULT '',
            ai_decision TEXT DEFAULT 'Pending',
            user_decision TEXT DEFAULT 'Keep',
            reasoning TEXT,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            pdf_status TEXT DEFAULT 'Pending',
            pdf_path TEXT DEFAULT NULL,
            full_text_decision TEXT DEFAULT 'Pending',
            full_text_user_decision TEXT DEFAULT 'Keep',
            pico_evidence TEXT DEFAULT NULL,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS project_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            data_type TEXT NOT NULL,
            data_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
            UNIQUE(project_id, data_type)
        );

        CREATE TRIGGER IF NOT EXISTS update_projects_timestamp
        AFTER UPDATE ON projects
        BEGIN
            UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;

        CREATE TRIGGER IF NOT EXISTS update_project_data_timestamp
        AFTER UPDATE ON project_data
        BEGIN
            UPDATE project_data SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
        """
    )

    # Ensure older DBs gain columns added historically via one-off scripts or runtime ALTERs.
    for col, ddl in [
        ("doi", "TEXT DEFAULT ''"),
        ("abstract", "TEXT DEFAULT ''"),
        ("pdf_status", "TEXT DEFAULT 'Pending'"),
        ("pdf_path", "TEXT DEFAULT NULL"),
        ("full_text_decision", "TEXT DEFAULT 'Pending'"),
        ("full_text_user_decision", "TEXT DEFAULT 'Keep'"),
        ("pico_evidence", "TEXT DEFAULT NULL"),
    ]:
        _ensure_column(conn, "literatures", col, ddl)


def init_database(db_path: str | Path | None = None) -> Path:
    """Initialize a new DB file (creates tables and required columns)."""
    path = Path(db_path) if db_path is not None else default_db_path()
    conn = connect(path)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def upgrade_database(db_path: str | Path | None = None) -> None:
    """Upgrade an existing DB in-place to the latest schema."""
    conn = connect(db_path)
    try:
        ensure_schema(conn)
        conn.commit()
    finally:
        conn.close()


# Backwards-compatible alias used by older code.
def get_db() -> sqlite3.Connection:
    return connect()


if __name__ == "__main__":
    path = init_database()
    print(f"Database ready at: {path}")

