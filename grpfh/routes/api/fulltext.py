# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from flask import request, send_file

from grpfh.database import connect
from grpfh.storage import is_within_directory, safe_storage_name

from . import bp
from ._context import get_paths, get_settings
from ._db_helpers import resolve_literature_context, resolve_project_context
from ._helpers import fail, json_body, ok


def _legacy_shared_pdf_path(paths, doi: str, paper_id: int) -> Path:
    filename = safe_storage_name(doi.replace("/", "_") + ".pdf", f"paper_{paper_id}.pdf")
    return paths.resources_root / "pdf" / filename


def _copy_legacy_pdf_into_project(paths, *, user_id: int, project_id: int, paper_id: int, doi: str) -> Path | None:
    legacy_pdf = _legacy_shared_pdf_path(paths, doi, paper_id)
    if not legacy_pdf.exists():
        return None

    target_dir = paths.project_pdf_dir(user_id, project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_pdf = target_dir / legacy_pdf.name

    if legacy_pdf.resolve() != target_pdf.resolve():
        shutil.copy2(legacy_pdf, target_pdf)

    return target_pdf


@bp.post("/fetch-pdfs")
def fetch_pdfs_api():
    data = json_body()
    project_id = data.get("project_id")
    user_id = data.get("user_id")
    if not project_id or not user_id:
        return fail("Project ID and user ID required")

    from Screening.paper_download import ImprovedPaperDownloader

    settings = get_settings()
    paths = get_paths()

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

        cursor.execute(
            """
            SELECT id, title, doi FROM literatures
            WHERE project_id = ?
              AND (user_decision = 'Include'
                   OR (COALESCE(user_decision, 'Keep') = 'Keep' AND ai_decision = 'Included'))
              AND (pdf_status = 'Pending' OR pdf_status IS NULL)
            """,
            (project["id"],),
        )
        papers = cursor.fetchall()

        if not papers:
            return ok(
                message="No included papers are ready for PDF download yet. Run abstract screening or mark papers as Include first.",
                count=0,
            )

        downloader = ImprovedPaperDownloader()
        output_dir = paths.project_storage_dir(project["user_id"], project["id"])
        os.makedirs(output_dir, exist_ok=True)

        success_count = 0
        for paper in papers:
            doi = paper["doi"]
            if not doi:
                cursor.execute("UPDATE literatures SET pdf_status = 'Failed (No DOI)' WHERE id = ?", (paper["id"],))
                continue

            migrated_pdf = _copy_legacy_pdf_into_project(
                paths,
                user_id=int(project["user_id"]),
                project_id=int(project["id"]),
                paper_id=int(paper["id"]),
                doi=str(doi),
            )
            if migrated_pdf is not None:
                cursor.execute(
                    "UPDATE literatures SET pdf_status = 'Downloaded', pdf_path = ? WHERE id = ?",
                    (str(migrated_pdf), paper["id"]),
                )
                success_count += 1
                continue

            downloaded = downloader.download_paper(doi, output_dir=str(output_dir))
            if downloaded:
                filename = safe_storage_name(doi.replace("/", "_") + ".pdf", f"paper_{paper['id']}.pdf")
                filepath = paths.project_pdf_dir(project["user_id"], project["id"]) / filename
                cursor.execute(
                    "UPDATE literatures SET pdf_status = 'Downloaded', pdf_path = ? WHERE id = ?",
                    (str(filepath), paper["id"]),
                )
                success_count += 1
            else:
                cursor.execute(
                    "UPDATE literatures SET pdf_status = 'Failed (Paywalled/Error)' WHERE id = ?",
                    (paper["id"],),
                )

        conn.commit()

    return ok(
        message=f"Attempted {len(papers)} downloads. Successfully fetched {success_count} PDFs.",
        count=success_count,
    )


@bp.post("/upload-pdf")
def upload_pdf():
    paper_id = request.form.get("paper_id")
    user_id = request.form.get("user_id")
    file = request.files.get("file")

    if not file:
        return fail("No file uploaded")
    if not paper_id or not user_id:
        return fail("Paper ID and user ID required")

    settings = get_settings()
    paths = get_paths()

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        paper, error = resolve_literature_context(cursor, int(paper_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

        doi = paper["doi"]
        filename = doi.replace("/", "_") + ".pdf" if doi else f"manual_upload_{paper_id}.pdf"
        filename = safe_storage_name(filename, f"paper_{paper_id}.pdf")

        save_dir = paths.project_pdf_dir(paper["user_id"], paper["project_id"])
        os.makedirs(save_dir, exist_ok=True)

        filepath = save_dir / filename
        file.save(str(filepath))

        import fitz

        original_filename = file.filename if file.filename else f"Manual Upload {paper_id}"
        new_title = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename

        try:
            with fitz.open(str(filepath)) as doc:
                meta_title = str(doc.metadata.get("title") or "").strip()
                
                if len(meta_title) >= 6 and "untitled" not in meta_title.lower():
                    new_title = meta_title
                elif doc.page_count > 0:
                    first_page_text = doc[0].get_text("text").strip()
                    for line in first_page_text.split("\n"):
                        line = line.strip()
                        if len(line) >= 10:
                            new_title = line[:300]
                            break
        except Exception as e:
            print(f"PDF Title extraction failed for {filepath}: {e}")

        cursor.execute(
            """
            UPDATE literatures
            SET pdf_status = 'Downloaded', pdf_path = ?, title = ?
            WHERE id = ?
            """,
            (str(filepath), new_title, paper_id),
        )
        conn.commit()

    return ok(message="PDF uploaded successfully and real title extracted")

@bp.post("/run-fulltext-ai")
def run_fulltext_ai_api():
    data = json_body()
    project_id = data.get("project_id")
    user_id = data.get("user_id")
    if not project_id or not user_id:
        return fail("Project ID and user ID required")

    from Screening.FullTextScreening import run_fulltext_ai_sync

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

        cursor.execute(
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'pico'",
            (project_id,),
        )
        pico_row = cursor.fetchone()
        pico_data = json.loads(pico_row["data_content"]) if pico_row else {}

        cursor.execute(
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'protocol'",
            (project_id,),
        )
        protocol_row = cursor.fetchone()
        if protocol_row:
            protocol_data = json.loads(protocol_row["data_content"])
            pico_data["es"] = protocol_data.get("criteria", "")
        else:
            pico_data["es"] = ""

        cursor.execute(
            """
            SELECT id, title, pdf_path
            FROM literatures
            WHERE project_id = ?
              AND pdf_status = 'Downloaded'
              AND (full_text_decision = 'Pending' OR full_text_decision IS NULL)
            """,
            (project_id,),
        )
        papers = cursor.fetchall()
        if not papers:
            return ok(message="No pending downloaded papers to screen.", count=0)

        papers_to_screen = [{"id": p["id"], "title": p["title"], "pdf_path": p["pdf_path"]} for p in papers]

        cursor.execute(
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'project_type'",
            (project_id,),
        )
        pt_row = cursor.fetchone()
        project_type = json.loads(pt_row["data_content"]) if pt_row else "PICOS"
        if project_type == "SPICO":
            project_type = "PICOS"

        results = run_fulltext_ai_sync(papers_to_screen, pico_data, project_type)

        success_count = 0
        for idx, res in enumerate(results):
            if res.get("decision") != "Error":
                original_pdf = papers_to_screen[idx]["pdf_path"]
                final_pdf_path = res.get("hl_path") or original_pdf
                cursor.execute(
                    """
                    UPDATE literatures
                    SET full_text_decision = ?, pico_evidence = ?, pdf_path = ?
                    WHERE id = ?
                    """,
                    (res.get("decision"), res.get("evidence"), final_pdf_path, res.get("id")),
                )
                success_count += 1

        conn.commit()

    return ok(message=f"AI Processed {success_count} full-text papers.", count=success_count)


@bp.get("/view-pdf")
def view_pdf():
    literature_id = request.args.get("literature_id")
    user_id = request.args.get("user_id")
    if not literature_id or not user_id:
        return "Missing literature ID or user ID", 400

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        literature, error = resolve_literature_context(cursor, int(literature_id), int(user_id))
        if error:
            return error[0], error[1]

    pdf_path = literature["pdf_path"]
    if not pdf_path:
        return "PDF not found on server", 404

    candidate = Path(str(pdf_path))
    if not is_within_directory(candidate, settings.resources_root):
        return "PDF path is not allowed", 403

    if candidate.exists():
        return send_file(str(candidate), mimetype="application/pdf")
    return "PDF not found on server", 404
