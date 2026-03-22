from __future__ import annotations

import json

from grpfh.database import connect

from . import bp
from ._context import get_settings
from ._db_helpers import resolve_project_context
from ._helpers import fail, json_body, ok


@bp.post("/upload-literature")
def upload_literature():
    data = json_body()
    project_id = data.get("project_id")
    title = data.get("title")
    author = data.get("author", "")
    journal = data.get("journal", "")
    year = data.get("year")
    doi = data.get("doi", "")
    abstract = data.get("abstract", "")

    if not project_id or not title:
        return fail("Project ID and Literature title cannot be empty!")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM literatures WHERE project_id = ? AND title = ?", (project_id, title))
        if cursor.fetchone():
            return ok(inserted=False, message="Duplicate literature skipped.")

        cursor.execute(
            """
            INSERT INTO literatures
            (project_id, title, author, journal, year, doi, abstract, ai_decision, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                title,
                author,
                journal,
                year,
                doi,
                abstract,
                "Pending",
                "Waiting for AI screening...",
            ),
        )
        conn.commit()

    return ok(inserted=True, message="Literature uploaded successfully!")


@bp.post("/search-pubmed")
def api_search_pubmed():
    data = json_body()
    project_id = data.get("project_id")
    keywords = data.get("keywords")
    max_papers = data.get("max_papers", 200)
    databases = data.get("databases", ["pubmed", "openalex", "wos"])

    if not project_id or not keywords:
        return fail("Project ID and keywords are required")

    try:
        from Screening.abstract_screening.literature_search import literature_search_all

        papers = literature_search_all(keywords, max_papers, databases=databases)
    except Exception as e:
        return fail(f"Search failed: {str(e)}", status=500)

    if not papers:
        return ok(message="No literatures found for these keywords.", count=0)

    settings = get_settings()
    inserted_count = 0
    duplicate_count = 0

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()

        for paper in papers:
            if not paper.get("title"):
                continue

            cursor.execute(
                "SELECT id FROM literatures WHERE project_id = ? AND title = ?",
                (project_id, paper["title"]),
            )
            if cursor.fetchone():
                duplicate_count += 1
                continue

            cursor.execute(
                """
                INSERT INTO literatures
                (project_id, title, author, journal, year, doi, abstract, ai_decision, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    paper.get("title", ""),
                    paper.get("author", ""),
                    paper.get("journal", ""),
                    paper.get("year"),
                    paper.get("doi", ""),
                    paper.get("abstract", ""),
                    "Pending",
                    "Waiting for AI screening...",
                ),
            )
            inserted_count += 1

        conn.commit()

    msg = f"Successfully saved {inserted_count} new papers."
    if duplicate_count > 0:
        msg += f" (Skipped {duplicate_count} duplicate papers)."

    return ok(message=msg, count=inserted_count)


@bp.post("/get-literatures")
def get_literatures():
    data = json_body()
    project_id = data.get("project_id")
    user_id = data.get("user_id")

    if not project_id or not user_id:
        return fail("Project ID and user ID required")

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

        cursor.execute(
            """
            SELECT id, title, author, journal, year, doi, abstract, ai_decision, user_decision, reasoning,
                   pdf_status, pdf_path, full_text_decision, full_text_user_decision, pico_evidence
            FROM literatures
            WHERE project_id = ?
            ORDER BY id ASC
            """,
            (project["id"],),
        )
        rows = cursor.fetchall()

    return ok(data=[dict(r) for r in rows])


@bp.post("/update-literature-decision")
def update_literature_decision():
    data = json_body()
    literature_id = data.get("literature_id")
    user_decision = data.get("user_decision")
    reasoning = data.get("reasoning")
    full_text_user_decision = data.get("full_text_user_decision")

    if not literature_id:
        return fail("Literature ID required")

    updates: list[str] = []
    params: list[object] = []
    if user_decision is not None:
        updates.append("user_decision = ?")
        params.append(user_decision)
    if reasoning is not None:
        updates.append("reasoning = ?")
        params.append(reasoning)
    if full_text_user_decision is not None:
        updates.append("full_text_user_decision = ?")
        params.append(full_text_user_decision)

    if not updates:
        return fail("Nothing to update")

    params.append(literature_id)

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE literatures SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()

    return ok("Decision updated successfully")

