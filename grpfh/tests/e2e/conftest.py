from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterator

import pytest
from werkzeug.serving import make_server

from grpfh.app import create_app
from grpfh.settings import Settings


@pytest.fixture(scope="module")
def live_server(tmp_path_factory) -> Iterator[str]:
    tmp = tmp_path_factory.mktemp("e2e")
    settings = Settings(
        host="127.0.0.1",
        port=3000,
        debug=False,
        db_path=tmp / "test.db",
        resources_root=tmp / "resources",
        outputs_root=tmp / "outputs",
        cors_origins="*",
        max_content_length_bytes=None,
    )
    app = create_app(settings)
    app.config.update(TESTING=False)

    server = make_server("127.0.0.1", 0, app)
    port = int(server.server_port)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def app_page(page, live_server: str):
    """A Playwright page already navigated to the app, with API URL rewriting enabled.

    The frontend hardcodes API calls to http://localhost:3000 when served from 127.0.0.1,
    so we rewrite those requests to the dynamic live_server port.
    """

    # Use context routing for base-URL rewrite so tests can still use page.route()
    # to mock specific endpoints when needed.
    ctx = page.context

    def _abort_cdn(route):
        return route.abort()

    def _rewrite_localhost(route):
        url = route.request.url
        new_url = live_server + url.removeprefix("http://localhost:3000")
        return route.continue_(url=new_url)

    def _rewrite_127(route):
        url = route.request.url
        new_url = live_server + url.removeprefix("http://127.0.0.1:3000")
        return route.continue_(url=new_url)

    ctx.route("https://cdnjs.cloudflare.com/**", _abort_cdn)
    ctx.route("http://localhost:3000/**", _rewrite_localhost)
    ctx.route("http://127.0.0.1:3000/**", _rewrite_127)

    page.grpfh_base_url = live_server  # type: ignore[attr-defined]
    page.goto(live_server, wait_until="domcontentloaded")
    return page
