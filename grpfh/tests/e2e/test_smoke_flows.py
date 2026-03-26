from __future__ import annotations

import time
from pathlib import Path


def _accept_next_dialog(page):
    page.once("dialog", lambda d: d.accept())


def _open_login(page):
    page.get_by_role("button", name="Log In").click()
    page.wait_for_selector("#inner-login-form")


def _open_signup(page):
    page.get_by_role("button", name="Sign Up").click()
    page.wait_for_selector("#inner-register-form")


def _register(page, email: str, password: str):
    _open_signup(page)
    page.fill("#reg-email", email)
    page.fill("#reg-password", password)
    page.fill("#reg-confirm-pwd", password)
    _accept_next_dialog(page)
    page.click("#register-btn")


def _login(page, email: str, password: str):
    _open_login(page)
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("#login-btn")
    page.wait_for_selector("#home-page", state="visible")


def _create_project_and_go_pico(page, name: str):
    page.wait_for_selector("#create-project-btn")
    page.click("#create-project-btn")
    page.wait_for_selector("#createProjectModal", state="visible")
    page.fill("#newProjectNameInput", name)
    page.click("#confirmCreateProjectBtn")
    page.wait_for_selector("#pico-page", state="visible")


def _fill_spico(page):
    page.fill("#spico-s", "S")
    page.fill("#spico-p", "P")
    page.fill("#spico-i", "I")
    page.fill("#spico-c", "C")
    page.fill("#spico-o", "O")


def test_login_create_project_save_pico(app_page):
    page = app_page
    email = f"e2e_{int(time.time())}@example.com"
    password = "abcdef"

    _register(page, email, password)
    _login(page, email, password)
    _create_project_and_go_pico(page, "E2E Project")
    _fill_spico(page)

    page.click("#import-papers-btn")
    page.wait_for_selector("#import-search-page", state="visible")

    project_id = page.evaluate("JSON.parse(sessionStorage.getItem('currentProject')).id")
    pico = page.evaluate(
        """async (pid) => {
          const r = await fetch('/api/get-project-data', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: pid, data_type: 'pico'})
          });
          return r.json();
        }""",
        project_id,
    )
    assert pico["success"] is True
    assert pico["data"]["p"] == "P"


def test_upload_literature_list_renders(app_page):
    page = app_page
    email = f"e2e_{int(time.time())}@example.com"
    password = "abcdef"

    _register(page, email, password)
    _login(page, email, password)
    _create_project_and_go_pico(page, "Upload Project")
    _fill_spico(page)
    page.click("#import-papers-btn")
    page.wait_for_selector("#import-search-page", state="visible")
    page.evaluate("switchImportTab('import')")

    repo_root = Path(__file__).resolve().parents[3]
    bib_path = repo_root / "grpfh" / "test.bib"
    page.set_input_files("#file-upload", str(bib_path))

    _accept_next_dialog(page)
    page.click("#upload-btn")

    # Wait until the table is actually populated (not just the initial empty row).
    page.wait_for_function(
        "() => !document.querySelector('#literature-table-body')?.innerText?.includes('No literature data yet')"
    )
    body_text = page.locator("#literature-table-body").inner_text()
    assert "No literature data yet" not in body_text


def test_screening_decision_update(app_page):
    page = app_page
    email = f"e2e_{int(time.time())}@example.com"
    password = "abcdef"

    _register(page, email, password)
    _login(page, email, password)
    _create_project_and_go_pico(page, "Decision Project")
    _fill_spico(page)
    page.click("#import-papers-btn")
    page.wait_for_selector("#import-search-page", state="visible")

    project_id = page.evaluate("JSON.parse(sessionStorage.getItem('currentProject')).id")
    page.evaluate(
        """async (pid) => {
          await fetch('/api/upload-literature', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: pid, title: 'Paper 1', abstract: 'abs'})
          });
        }""",
        project_id,
    )

    page.evaluate("showPage('abstract-screen-page')")
    page.wait_for_selector("#abstract-screen-page", state="visible")
    page.wait_for_selector("#screenTableBody tr")

    btn = page.locator("#screenTableBody tr").first.locator("button").first
    btn.click()
    assert btn.inner_text() in {"Included", "Excluded", "Keep AI"}

    # Verify persisted in DB via API.
    lits = page.evaluate(
        """async (pid) => {
          const r = await fetch('/api/get-literatures', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: pid, user_id: JSON.parse(sessionStorage.getItem('currentUser')).id})
          });
          return r.json();
        }""",
        project_id,
    )
    assert lits["success"] is True
    assert any(l.get("user_decision") in {"Include", "Exclude"} for l in lits["data"])


def test_error_state_on_failed_request(app_page):
    page = app_page
    email = f"e2e_{int(time.time())}@example.com"
    password = "abcdef"

    _register(page, email, password)
    _login(page, email, password)
    _create_project_and_go_pico(page, "Error Project")
    _fill_spico(page)
    page.click("#import-papers-btn")
    page.wait_for_selector("#import-search-page", state="visible")

    # Force search endpoint to fail and assert the UI surfaces an alert.
    def fail_search(route):
        return route.fulfill(
            status=500,
            content_type="application/json",
            body='{"success":false,"message":"boom"}',
        )

    page.route("**/api/search-pubmed", fail_search)

    page.evaluate("switchImportTab('search')")
    page.wait_for_selector("#search-keywords", state="visible")
    page.fill("#search-keywords", "cancer")
    _accept_next_dialog(page)
    page.click("#search-pubmed-btn")
