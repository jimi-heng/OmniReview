# Author: Team 04
# This file is developed by our team

from __future__ import annotations

from typing import Any

from flask import jsonify, request


def json_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def ok(message: str | None = None, **data: Any):
    payload: dict[str, Any] = {"success": True}
    if message is not None:
        payload["message"] = message
    payload.update(data)
    return jsonify(payload)


def fail(message: str, status: int = 400, **data: Any):
    payload: dict[str, Any] = {"success": False, "message": message}
    payload.update(data)
    return jsonify(payload), status

