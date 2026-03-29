# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import json

from grpfh.database import connect

from . import bp
from ._context import get_settings
from ._helpers import fail, json_body, ok


@bp.post("/get-projects")
def get_projects():
    data = json_body()
    user_id = data.get("user_id")
    if not user_id:
        return fail("User ID required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id, p.project_name, p.status, p.created_at, pd.data_content as project_type
            FROM projects p
            LEFT JOIN project_data pd ON p.id = pd.project_id AND pd.data_type = 'project_type'
            WHERE p.user_id = ?
            ORDER BY p.updated_at DESC
            LIMIT 5
            """,
            (user_id,),
        )
        rows = cursor.fetchall()

    projects: list[dict] = []
    for row in rows:
        project = dict(row)
        if project.get("created_at"):
            project["created_at"] = str(project["created_at"])[:10]
        projects.append(project)

    return ok(data=projects)


@bp.post("/create-project")
def create_project():
    data = json_body()
    user_id = data.get("user_id")
    project_name = data.get("project_name")
    if not user_id or not project_name:
        return fail("User ID and project name required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO projects (user_id, project_name, status)
            VALUES (?, ?, ?)
            """,
            (user_id, project_name, "PICO Setup"),
        )
        project_id = cursor.lastrowid
        conn.commit()

    return ok("Project created successfully", project_id=project_id)


@bp.post("/save-project-data")
def save_project_data():
    data = json_body()
    project_id = data.get("project_id")
    data_type = data.get("data_type")
    data_content = data.get("data_content")
    if not project_id or not data_type or data_content is None:
        return fail("Missing required fields")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO project_data (project_id, data_type, data_content)
            VALUES (?, ?, ?)
            """,
            (project_id, data_type, json.dumps(data_content, ensure_ascii=False)),
        )
        cursor.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
        conn.commit()

    return ok("Data saved successfully")


@bp.post("/get-project-data")
def get_project_data():
    data = json_body()
    project_id = data.get("project_id")
    data_type = data.get("data_type")
    if not project_id:
        return fail("Project ID required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
        conn.commit()

        if data_type:
            cursor.execute(
                """
                SELECT data_content FROM project_data
                WHERE project_id = ? AND data_type = ?
                """,
                (project_id, data_type),
            )
            result = cursor.fetchone()
            if result and result["data_content"] is not None:
                return ok(data=json.loads(result["data_content"]))
            return ok(data=None)

        cursor.execute(
            """
            SELECT data_type, data_content
            FROM project_data
            WHERE project_id = ?
            """,
            (project_id,),
        )
        rows = cursor.fetchall()

    all_data: dict[str, object] = {}
    for row in rows:
        all_data[row["data_type"]] = json.loads(row["data_content"]) if row["data_content"] else None
    return ok(data=all_data)


@bp.post("/update-project-status")
def update_project_status():
    data = json_body()
    project_id = data.get("project_id")
    status = data.get("status")
    if not project_id or not status:
        return fail("Project ID and status required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
        conn.commit()

    return ok("Project status updated successfully")


@bp.post("/update-project-name")
def update_project_name():
    data = json_body()
    project_id = data.get("project_id")
    project_name = data.get("project_name")
    if not project_id or not project_name:
        return fail("Missing required fields")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE projects SET project_name = ? WHERE id = ?", (project_name, project_id))
        conn.commit()

    return ok("Project name updated successfully")


@bp.post("/delete-project")
def delete_project():
    data = json_body()
    project_id = data.get("project_id")
    if not project_id:
        return fail("Project ID required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()

    return ok("Project deleted successfully")

