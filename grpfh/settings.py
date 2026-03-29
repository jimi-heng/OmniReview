# Author: Team 04
# This file is developed by our team

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _repo_root() -> Path:
    # grpfh/ is a top-level folder inside the repo.
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Settings:
    host: str
    port: int
    debug: bool
    db_path: Path
    resources_root: Path
    outputs_root: Path
    cors_origins: str | list[str]
    max_content_length_bytes: int | None


def load_settings() -> Settings:
    root = _repo_root()

    host = os.getenv("GRPFH_HOST", "127.0.0.1")
    port = int(os.getenv("GRPFH_PORT", "3000"))
    debug = os.getenv("GRPFH_DEBUG", "true").lower() in {"1", "true", "yes", "y", "on"}

    db_path = Path(os.getenv("GRPFH_DB_PATH", str(root / "ai_screening.db"))).resolve()
    resources_root = Path(os.getenv("GRPFH_RESOURCES_ROOT", str(root / "resources"))).resolve()
    outputs_root = Path(os.getenv("GRPFH_OUTPUTS_ROOT", str(root / "outputs"))).resolve()

    cors_origins_env = os.getenv("GRPFH_CORS_ORIGINS", "*").strip()
    cors_origins: str | list[str] = cors_origins_env

    max_mb = os.getenv("GRPFH_MAX_UPLOAD_MB", "").strip()
    max_content_length_bytes = int(max_mb) * 1024 * 1024 if max_mb.isdigit() else None

    return Settings(
        host=host,
        port=port,
        debug=debug,
        db_path=db_path,
        resources_root=resources_root,
        outputs_root=outputs_root,
        cors_origins=cors_origins,
        max_content_length_bytes=max_content_length_bytes,
    )

