from __future__ import annotations

from grpfh.database import connect
from grpfh.routes.api._db_helpers import resolve_literature_context, resolve_project_context


def test_resolve_project_found(app, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        conn.commit()

        p, err = resolve_project_context(cur, int(proj_id), int(user_id))
        assert err is None
        assert p is not None
        assert int(p["id"]) == int(proj_id)


def test_resolve_project_not_found(app, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        p, err = resolve_project_context(cur, 999, 1)
        assert p is None
        assert err == ("Project not found", 404)


def test_resolve_project_wrong_user(app, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO users (email, password) VALUES ('b@b', 'y')")
        other = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        conn.commit()

        p, err = resolve_project_context(cur, int(proj_id), int(other))
        assert p is None
        assert err == ("Project does not belong to current user", 403)


def test_resolve_literature_found(app, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, password) VALUES ('a@a', 'x')")
        user_id = cur.lastrowid
        cur.execute("INSERT INTO projects (user_id, project_name) VALUES (?, 'p')", (user_id,))
        proj_id = cur.lastrowid
        cur.execute("INSERT INTO literatures (project_id, title) VALUES (?, 't')", (proj_id,))
        lit_id = cur.lastrowid
        conn.commit()

        l, err = resolve_literature_context(cur, int(lit_id), int(user_id))
        assert err is None
        assert l is not None
        assert int(l["id"]) == int(lit_id)


def test_resolve_literature_not_found(app, settings):
    with connect(settings.db_path) as conn:
        cur = conn.cursor()
        l, err = resolve_literature_context(cur, 999, 1)
        assert l is None
        assert err == ("Paper not found", 404)
