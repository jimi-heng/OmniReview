from __future__ import annotations

from datetime import datetime

from grpfh.database import connect

from ._context import get_settings
from ._helpers import ok, fail
from flask import Blueprint


bp = Blueprint("admin", __name__)


@bp.get("/stats")
def get_admin_stats():
    settings = get_settings()
    try:
        with connect(settings.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, created_at FROM users")
            all_users = cursor.fetchall()

            cursor.execute(
                """
                SELECT p.id, p.created_at, pd.data_content as project_type
                FROM projects p
                LEFT JOIN project_data pd ON p.id = pd.project_id AND pd.data_type = 'project_type'
                """
            )
            all_projects = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM literatures")
            total_papers_count = cursor.fetchone()[0]

        now = datetime.now()

        def stats_structure():
            return {
                "users": 0,
                "projects": {"SPICO": 0, "PECO": 0, "PIRO": 0, "total_proj": 0},
                "papers": 0,
            }

        dataset = {"today": stats_structure(), "week": stats_structure(), "month": stats_structure(), "all": stats_structure()}

        for u in all_users:
            created_at_str = u["created_at"] if hasattr(u, "keys") else u[1]
            try:
                created_at = datetime.strptime(str(created_at_str).split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = now
            diff_days = (now - created_at).days

            if diff_days <= 1:
                dataset["today"]["users"] += 1
            if diff_days <= 7:
                dataset["week"]["users"] += 1
            if diff_days <= 30:
                dataset["month"]["users"] += 1
            dataset["all"]["users"] += 1

        for p in all_projects:
            p_type_raw = p["project_type"] if hasattr(p, "keys") else p[2]
            created_at_str = p["created_at"] if hasattr(p, "keys") else p[1]

            p_type = str(p_type_raw).replace('"', "").upper() if p_type_raw else "SPICO"
            if p_type not in ["SPICO", "PECO", "PIRO"]:
                p_type = "SPICO"

            try:
                created_at = datetime.strptime(str(created_at_str).split(".")[0], "%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = now
            diff_days = (now - created_at).days

            def fill_proj_data(range_key: str):
                dataset[range_key]["projects"][p_type] += 1
                dataset[range_key]["projects"]["total_proj"] += 1

            if diff_days <= 1:
                fill_proj_data("today")
            if diff_days <= 7:
                fill_proj_data("week")
            if diff_days <= 30:
                fill_proj_data("month")
            fill_proj_data("all")

        dataset["all"]["papers"] = total_papers_count
        total_proj = dataset["all"]["projects"]["total_proj"]
        if total_proj > 0:
            dataset["today"]["papers"] = round(total_papers_count * dataset["today"]["projects"]["total_proj"] / total_proj)
            dataset["week"]["papers"] = round(total_papers_count * dataset["week"]["projects"]["total_proj"] / total_proj)
            dataset["month"]["papers"] = round(total_papers_count * dataset["month"]["projects"]["total_proj"] / total_proj)
        else:
            dataset["today"]["papers"] = dataset["week"]["papers"] = dataset["month"]["papers"] = 0

        return ok(data=dataset)

    except Exception as e:
        return fail(str(e), status=500)

