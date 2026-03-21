from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, send_file, send_from_directory

from grpfh.storage import is_within_directory


bp = Blueprint("frontend", __name__)

_ALLOWED_EXTS = {
    ".html",
    ".js",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".svg",
    ".gif",
    ".ico",
    ".json",
    ".txt",
    ".woff",
    ".woff2",
    ".ttf",
}

_DENY_NAMES = {
    "ai_screening.db",
    ".env",
    ".python-version",
    "pyproject.toml",
    "uv.lock",
}


def _public_root() -> Path:
    # Files currently live directly under grpfh/ (index.html, script.js, css/, js/, etc.)
    return Path(__file__).resolve().parents[1]


@bp.get("/")
def index():
    root = _public_root()
    return send_file(root / "index.html")


@bp.get("/<path:filename>")
def static_files(filename: str):
    root = _public_root()
    candidate = (root / filename)

    if candidate.name in _DENY_NAMES:
        abort(404)

    if not is_within_directory(candidate, root):
        abort(404)

    if candidate.suffix.lower() not in _ALLOWED_EXTS:
        abort(404)

    if not candidate.exists() or not candidate.is_file():
        abort(404)

    # send_from_directory uses safe-join semantics, but we already validated path.
    return send_from_directory(str(root), filename)

