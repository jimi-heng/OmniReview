from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from werkzeug.utils import secure_filename


def safe_storage_name(value: str | None, fallback: str) -> str:
    cleaned = secure_filename(str(value or "").strip())
    return cleaned or fallback


def is_within_directory(candidate_path: Path, base_dir: Path) -> bool:
    try:
        return candidate_path.resolve().is_relative_to(base_dir.resolve())
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    resources_root: Path
    outputs_root: Path

    def project_storage_dir(self, user_id: int, project_id: int) -> Path:
        return self.resources_root / "users" / f"user_{int(user_id)}" / "projects" / f"project_{int(project_id)}"

    def project_output_dir(self, user_id: int, project_id: int) -> Path:
        return self.outputs_root / "users" / f"user_{int(user_id)}" / "projects" / f"project_{int(project_id)}"

    def project_pdf_dir(self, user_id: int, project_id: int) -> Path:
        return self.project_storage_dir(user_id, project_id) / "pdf"

    def project_extraction_dir(self, user_id: int, project_id: int) -> Path:
        return self.project_storage_dir(user_id, project_id) / "extraction_inputs"

    def project_output_paths(self, user_id: int, project_id: int) -> tuple[Path, Path]:
        out_dir = self.project_output_dir(user_id, project_id)
        return (
            out_dir / f"proj_{project_id}_extracted.csv",
            out_dir / f"proj_{project_id}_extracted.xlsx",
        )

