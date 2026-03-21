from __future__ import annotations

import sqlite3


def resolve_project_context(
    cursor: sqlite3.Cursor, project_id: int, user_id: int | None = None
) -> tuple[sqlite3.Row | None, tuple[str, int] | None]:
    cursor.execute(
        """
        SELECT p.id, p.user_id, p.project_name
        FROM projects p
        WHERE p.id = ?
        """,
        (project_id,),
    )
    project = cursor.fetchone()
    if not project:
        return None, ("Project not found", 404)

    if user_id is not None and int(project["user_id"]) != int(user_id):
        return None, ("Project does not belong to current user", 403)

    return project, None


def resolve_literature_context(
    cursor: sqlite3.Cursor, literature_id: int, user_id: int | None = None
) -> tuple[sqlite3.Row | None, tuple[str, int] | None]:
    cursor.execute(
        """
        SELECT l.id, l.project_id, l.doi, l.pdf_path, p.user_id
        FROM literatures l
        JOIN projects p ON p.id = l.project_id
        WHERE l.id = ?
        """,
        (literature_id,),
    )
    literature = cursor.fetchone()
    if not literature:
        return None, ("Paper not found", 404)

    if user_id is not None and int(literature["user_id"]) != int(user_id):
        return None, ("Paper does not belong to current user", 403)

    return literature, None

