from __future__ import annotations

from grpfh.routes.api._helpers import fail, json_body, ok


def test_ok_minimal(app):
    with app.test_request_context("/x"):
        resp = ok()
        data = resp.get_json()
        assert data == {"success": True}


def test_ok_with_message_and_data(app):
    with app.test_request_context("/x"):
        resp = ok("msg", count=5)
        data = resp.get_json()
        assert data["success"] is True
        assert data["message"] == "msg"
        assert data["count"] == 5


def test_fail_default_400(app):
    with app.test_request_context("/x"):
        resp, status = fail("err")
        assert status == 400
        data = resp.get_json()
        assert data["success"] is False
        assert data["message"] == "err"


def test_fail_custom_status(app):
    with app.test_request_context("/x"):
        resp, status = fail("err", 404)
        assert status == 404


def test_json_body_valid(app):
    with app.test_request_context("/x", json={"a": 1}):
        assert json_body() == {"a": 1}


def test_json_body_non_dict(app):
    with app.test_request_context("/x", json=[1, 2]):
        assert json_body() == {}

