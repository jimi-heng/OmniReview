from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from flask import request, send_file

from grpfh.database import connect

from . import bp
from ._context import get_paths, get_settings
from ._db_helpers import resolve_project_context
from ._helpers import fail, json_body, ok


@bp.post("/run-data-extraction")
def run_data_extraction():
    data = json_body()
    project_id = data.get("project_id")
    user_id = data.get("user_id")
    if not project_id or not user_id:
        return fail("Project ID and user ID required")

    settings = get_settings()
    paths = get_paths()

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

        cursor.execute(
            """
            SELECT id, title, pdf_path
            FROM literatures
            WHERE project_id = ?
              AND (full_text_user_decision = 'Include'
                   OR (COALESCE(full_text_user_decision, 'Keep') = 'Keep' AND full_text_decision = 'Included'))
            """,
            (project_id,),
        )
        papers = cursor.fetchall()

    if not papers:
        return fail("No included papers found for extraction.")

    extract_dir = paths.project_extraction_dir(project["user_id"], project["id"])
    os.makedirs(extract_dir, exist_ok=True)

    for f in os.listdir(extract_dir):
        try:
            os.remove(os.path.join(extract_dir, f))
        except Exception:
            pass

    valid_count = 0
    for p in papers:
        src_path = p["pdf_path"]
        if src_path and os.path.exists(src_path):
            file_name = os.path.basename(src_path)
            dst_path = os.path.join(extract_dir, file_name)
            shutil.copy2(src_path, dst_path)
            valid_count += 1

    if valid_count == 0:
        return fail("Found included papers, but their PDF files are physically missing.")

    out_dir = paths.project_output_dir(project["user_id"], project["id"])
    os.makedirs(out_dir, exist_ok=True)
    out_csv, out_xlsx = paths.project_output_paths(project["user_id"], project["id"])

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
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
            "SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'project_type'",
            (project_id,),
        )
        pt_row = cursor.fetchone()
        project_type = json.loads(pt_row["data_content"]) if pt_row else "PICOS"

    if project_type == "SPICO":
        project_type = "PICOS"

    pico_json_str = json.dumps(pico_data, ensure_ascii=False)
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "Screening" / "EnhancedDataExtraction.py"

    python_exe = sys.executable
    if "uwsgi" in python_exe:
        python_exe = str(Path(python_exe).parent / "python")

    cmd = [
        python_exe,
        str(script_path),
        "--resources-dir",
        str(extract_dir),
        "--output-csv",
        str(out_csv),
        "--output-xlsx",
        str(out_xlsx),
        "--project-type",
        project_type,
        "--pico-json",
        pico_json_str,
        "--pipeline-mode",
        "phase2",
    ]

    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        error_msg = (process.stderr or "").strip() or (process.stdout or "").strip()
        short_err = error_msg[-300:] if len(error_msg) > 300 else error_msg
        return fail(f"Script crashed!\nReason: ...{short_err}")

    return ok(message=f"Successfully extracted nested data from {valid_count} papers!")


@bp.get("/download-extraction")
def download_extraction():
    project_id = request.args.get("project_id")
    user_id = request.args.get("user_id")
    file_type = request.args.get("type", "xlsx")
    if not project_id or not user_id:
        return "Project ID or user ID missing", 400

    settings = get_settings()
    paths = get_paths()

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return error[0], error[1]

    csv_path, xlsx_path = paths.project_output_paths(project["user_id"], project["id"])

    if file_type == "csv":
        file_path = csv_path
        mimetype = "text/csv"
    else:
        file_path = xlsx_path
        mimetype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    if os.path.exists(file_path):
        return send_file(str(file_path), as_attachment=True, mimetype=mimetype)
    return "File not found. Please run extraction first.", 404


@bp.get("/get-extraction-preview")
def get_extraction_preview():
    project_id = request.args.get("project_id")
    user_id = request.args.get("user_id")
    if not project_id or not user_id:
        return fail("Missing project ID or user ID")

    settings = get_settings()
    paths = get_paths()

    with connect(settings.db_path) as conn:
        cursor = conn.cursor()
        project, error = resolve_project_context(cursor, int(project_id), int(user_id))
        if error:
            return fail(error[0], status=error[1])

    csv_path, _ = paths.project_output_paths(project["user_id"], project["id"])
    if not os.path.exists(csv_path):
        return fail("Not extracted yet")

    try:
        df = pd.read_csv(str(csv_path)).fillna("")
        return ok(data=df.to_dict(orient="records"), columns=df.columns.tolist())
    except Exception as e:
        return fail(str(e), status=500)
