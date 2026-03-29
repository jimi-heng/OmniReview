# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import csv
from io import StringIO
import json

from flask import make_response, request

from grpfh.database import connect

from . import bp
from ._context import get_settings
from ._helpers import fail, json_body, ok


@bp.post("/run-ai-screening")
def run_ai_screening_api():
    data = json_body()
    project_id = data.get("project_id")
    if not project_id:
        return fail("Project ID required")

    from Screening.AbstractScreening import run_ai_screening_sync

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'pico'",
            (project_id,),
        )
        pico_row = cursor.fetchone()
        if not pico_row:
            return fail("PICO data not found. Please setup PICO first.")

        pico_data = json.loads(pico_row["data_content"])

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
            SELECT id, title, abstract, reasoning
            FROM literatures
            WHERE project_id = ? AND ai_decision IN ('Pending', 'Error')
            """,
            (project_id,),
        )
        pending_rows = cursor.fetchall()
        if not pending_rows:
            return ok(message="No pending literatures to screen.", count=0)

        papers_to_screen = [
            {
                "id": r["id"],
                "title": r["title"],
                "abstract": r["abstract"] if r["abstract"] else r["reasoning"],
            }
            for r in pending_rows
        ]

        cursor.execute(
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'project_type'",
            (project_id,),
        )
        pt_row = cursor.fetchone()
        project_type = json.loads(pt_row["data_content"]) if pt_row else "PICOS"
        if project_type == "SPICO":
            project_type = "PICOS"

        screen_results = run_ai_screening_sync(pico_data, papers_to_screen, project_type)

        for res in screen_results:
            final_decision = res.get("ai_decision")
            final_reasoning = res.get("reasoning", "")
            if "did not output detailed reasoning" in str(final_reasoning) or not final_decision:
                final_decision = "Error"
                final_reasoning = (
                    "⚠️ API connection failed or token limits reached. Please click the run button again to retry."
                )

            cursor.execute(
                """
                UPDATE literatures
                SET ai_decision = ?, reasoning = ?
                WHERE id = ?
                """,
                (final_decision, final_reasoning, res["id"]),
            )

        conn.commit()

    return ok(
        message=f"Successfully screened {len(screen_results)} papers using Multi-Agent workflow!",
        count=len(screen_results),
    )


@bp.get("/export-csv")
def export_csv():
    project_id = request.args.get("project_id")
    if not project_id:
        return fail("Project ID required", status=400)

    settings = get_settings()
    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT project_name FROM projects WHERE id = ?", (project_id,))
        project_row = cursor.fetchone()
        project_name = project_row["project_name"] if project_row else "project"

        cursor.execute(
            """
            SELECT id, title, author, journal, year, ai_decision, user_decision, reasoning
            FROM literatures
            WHERE project_id = ?
            ORDER BY id ASC
            """,
            (project_id,),
        )
        rows = cursor.fetchall()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(
        [
            "Database_ID",
            "Title",
            "Authors",
            "Journal",
            "Publication_Year",
            "AI_Decision",
            "User_Decision",
            "Reasoning/Abstract",
        ]
    )

    for row in rows:
        user_dec = row["user_decision"]
        ai_dec = row["ai_decision"]

        if user_dec == "Keep" or not user_dec:
            final_decision = ai_dec
        elif user_dec == "Include":
            final_decision = "Included"
        elif user_dec == "Exclude":
            final_decision = "Excluded"
        else:
            final_decision = user_dec

        cw.writerow(
            [
                row["id"],
                row["title"],
                row["author"],
                row["journal"],
                row["year"],
                row["ai_decision"],
                final_decision,
                row["reasoning"],
            ]
        )

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = (
        f"attachment; filename=screening_results_{str(project_name).replace(' ', '_')}.csv"
    )
    output.headers["Content-type"] = "text/csv; charset=utf-8-sig"
    return output

