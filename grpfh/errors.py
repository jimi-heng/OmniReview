from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def _handle_http_exc(e: HTTPException):
        # Keep response shape consistent for the frontend.
        return jsonify({"success": False, "message": e.description}), e.code

    @app.errorhandler(Exception)
    def _handle_uncaught(e: Exception):
        app.logger.exception("Unhandled error")
        return jsonify({"success": False, "message": "Internal server error"}), 500

