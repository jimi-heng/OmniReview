from __future__ import annotations

import time


def _accept_next_dialog(page):
    page.once("dialog", lambda d: d.accept())


def _login_quick(page):
    # Register via API directly to reduce UI steps for state tests.
    email = f"state_{int(time.time())}@example.com"
    password = "abcdef"
    page.evaluate(
        """async ({email, password}) => {
          await fetch('/api/register', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email, password})
          });
        }""",
        {"email": email, "password": password},
    )
    page.get_by_role("button", name="Log In").click()
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("#login-btn")
    page.wait_for_selector("#home-page", state="visible")
    return email


def _create_project_to_import(page):
    page.wait_for_selector("#create-project-btn")
    page.click("#create-project-btn")
    page.fill("#newProjectNameInput", "State Project")
    page.click("#confirmCreateProjectBtn")
    page.wait_for_selector("#pico-page", state="visible")
    page.fill("#spico-s", "S")
    page.fill("#spico-p", "P")
    page.fill("#spico-i", "I")
    page.fill("#spico-c", "C")
    page.fill("#spico-o", "O")
    page.click("#import-papers-btn")
    page.wait_for_selector("#import-search-page", state="visible")


def test_empty_state_literature_list(app_page):
    page = app_page
    _login_quick(page)
    _create_project_to_import(page)
    page.wait_for_selector("#literature-table-body")
    assert "No literature data yet" in page.locator("#literature-table-body").inner_text()


def test_loading_state_screening(app_page, mock_screening_modules):
    page = app_page
    _login_quick(page)
    _create_project_to_import(page)

    project_id = page.evaluate("JSON.parse(sessionStorage.getItem('currentProject')).id")
    user_id = page.evaluate("JSON.parse(sessionStorage.getItem('currentUser')).id")

    page.evaluate(
        """async (pid) => {
          await fetch('/api/upload-literature', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: pid, title: 'Pending 1', abstract: 'abs'})
          });
        }""",
        project_id,
    )

    # Configure mock to return an Included decision so the route completes successfully.
    # The actual DB id is discovered by the route, so a generic response is fine once we patch after fetch.
    mock_screening_modules.AbstractScreening.run_ai_screening_sync.side_effect = lambda pico, papers, project_type: [
        {"id": papers[0]["id"], "ai_decision": "Included", "reasoning": "ok"}
    ]

    page.evaluate("showPage('abstract-screen-page')")
    page.wait_for_selector("#abstract-screen-page", state="visible")

    # Slow down fetch in-page so the loading UI is stable (no routing precedence issues).
    page.evaluate(
        """() => {
          const orig = window.fetch.bind(window);
          window.fetch = async (...args) => {
            const a0 = args[0];
            const url = (typeof a0 === 'string') ? a0 : (a0 && a0.url) ? a0.url : '';
            if (String(url).includes('/api/run-ai-screening')) {
              await new Promise(r => setTimeout(r, 800));
            }
            return orig(...args);
          };
        }"""
    )

    btn = page.locator("#run-ai-screening-btn")
    _accept_next_dialog(page)
    btn.click()
    page.wait_for_function("() => document.querySelector('#run-ai-screening-btn')?.disabled === true")
    page.wait_for_function(
        "() => (document.querySelector('#run-ai-screening-btn')?.innerText || '').includes('AI is reading and screening')"
    )


def test_error_state_search_fail(app_page):
    page = app_page
    _login_quick(page)
    _create_project_to_import(page)

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


def test_success_state_after_screening(app_page, mock_screening_modules):
    page = app_page
    _login_quick(page)
    _create_project_to_import(page)

    project_id = page.evaluate("JSON.parse(sessionStorage.getItem('currentProject')).id")
    page.evaluate(
        """async (pid) => {
          await fetch('/api/upload-literature', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({project_id: pid, title: 'Pending 2', abstract: 'abs'})
          });
        }""",
        project_id,
    )

    mock_screening_modules.AbstractScreening.run_ai_screening_sync.side_effect = lambda pico, papers, project_type: [
        {"id": papers[0]["id"], "ai_decision": "Included", "reasoning": "ok"}
    ]

    page.evaluate("showPage('abstract-screen-page')")
    page.wait_for_selector("#abstract-screen-page", state="visible")
    page.wait_for_selector("#screenTableBody tr")

    _accept_next_dialog(page)
    page.click("#run-ai-screening-btn")

    # After refresh, AI decision column should show Included.
    page.wait_for_timeout(500)
    page.wait_for_function(
        """() => {
          const rows = document.querySelectorAll('#screenTableBody tr td:nth-child(3)');
          return Array.from(rows).some(td => (td.textContent || '').trim() === 'Included');
        }"""
    )
