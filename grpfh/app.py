from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask
from flask_cors import CORS

if __package__ in {None, ""}:
    # Keep `python grpfh/app.py` working while preserving package-qualified imports.
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

from grpfh.database import upgrade_database
from grpfh.errors import register_error_handlers
from grpfh.logging_config import configure_logging
from grpfh.settings import Settings, load_settings
from grpfh.storage import ProjectPaths


def _ensure_repo_root_on_syspath() -> None:
    # When running `python grpfh/app.py`, sys.path[0] is `.../grpfh`,
    # which breaks `import Screening...`. Keep legacy convenience working.
    repo_root = Path(__file__).resolve().parents[1]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def create_app(settings: Settings | None = None) -> Flask:
    _ensure_repo_root_on_syspath()

    settings = settings or load_settings()

    # Ensure DB schema is up to date before handling requests.
    upgrade_database(settings.db_path)

    # Disable Flask's implicit /static route since this repo serves a custom frontend.
    app = Flask(__name__, static_folder=None)

    if settings.max_content_length_bytes is not None:
        app.config["MAX_CONTENT_LENGTH"] = settings.max_content_length_bytes

    # Lightweight shared context for route modules.
    app.extensions["grpfh_settings"] = settings
    app.extensions["grpfh_paths"] = ProjectPaths(
        resources_root=settings.resources_root,
        outputs_root=settings.outputs_root,
    )

    configure_logging(app, settings.debug)
    register_error_handlers(app)

    # CORS is only needed for the API (local dev uses :3000 while static is file:// or another port).
    CORS(app, resources={r"/api/*": {"origins": settings.cors_origins}})

    from grpfh.routes.frontend import bp as frontend_bp
    from grpfh.routes.api import bp as api_bp
    from grpfh.routes.api.admin import bp as admin_bp

    app.register_blueprint(frontend_bp)
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")

    return app


def main() -> None:
    settings = load_settings()
    app = create_app(settings)

    app.logger.info("GRPFH backend starting at http://%s:%s", settings.host, settings.port)
    app.logger.info("DB: %s", settings.db_path)
    app.run(host=settings.host, port=settings.port, debug=settings.debug)


if __name__ == "__main__":
    main()
