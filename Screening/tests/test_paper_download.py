from __future__ import annotations

import os
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENING_DIR = ROOT_DIR / "Screening"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCREENING_DIR) not in sys.path:
    sys.path.insert(0, str(SCREENING_DIR))

from Screening.paper_download.cli import _dedupe_preserve_order, _read_dois_from_file
from Screening.paper_download import cli as paper_cli
from Screening.paper_download.downloader import DomainBackoff, ImprovedPaperDownloader, _extract_pii


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        url: str = "",
        text: str = "",
        headers: dict[str, str] | None = None,
        json_data: object | None = None,
        content: bytes | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.text = text
        self.headers = headers or {}
        self._json_data = json_data
        self._chunks = chunks or []
        self.content = content if content is not None else b"".join(self._chunks)

    def json(self):
        return self._json_data

    def iter_content(self, *, chunk_size: int = 8192):
        yield from self._chunks


class DomainBackoffTests(unittest.TestCase):
    def test_init_defaults(self) -> None:
        backoff = DomainBackoff()
        self.assertEqual(backoff.base, 0.5)
        self.assertEqual(backoff.cap, 30.0)
        self.assertEqual(backoff.jitter, 0.3)
        self.assertEqual(backoff.backoff_statuses, {429, 500, 502, 503, 504})

    def test_on_response_success_clears_state(self) -> None:
        backoff = DomainBackoff(jitter=0.0)
        backoff.on_response("example.com", 429)
        self.assertIn("example.com", backoff._state)
        backoff.on_response("example.com", 200)
        self.assertNotIn("example.com", backoff._state)

    def test_on_response_ignores_non_backoff_status(self) -> None:
        backoff = DomainBackoff(jitter=0.0)
        backoff.on_response("example.com", 404)
        self.assertEqual(backoff._state, {})

    def test_exponential_backoff_increments_fail_count(self) -> None:
        backoff = DomainBackoff(jitter=0.0)
        backoff.on_response("example.com", 429)
        fail_count, _ = backoff._state["example.com"]
        self.assertEqual(fail_count, 1)
        backoff.on_response("example.com", 500)
        fail_count, _ = backoff._state["example.com"]
        self.assertEqual(fail_count, 2)

    def test_backoff_respects_cap(self) -> None:
        backoff = DomainBackoff(base=1.0, cap=2.0, jitter=0.0)
        with (
            patch("Screening.paper_download.downloader.time.monotonic", return_value=0.0),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            for _ in range(10):
                backoff.on_response("example.com", 500)
        _, next_allowed = backoff._state["example.com"]
        self.assertLessEqual(next_allowed, 2.0)

    def test_wait_sleeps_when_next_allowed_in_future(self) -> None:
        backoff = DomainBackoff()
        backoff._state["example.com"] = (1, 10.0)
        with (
            patch("Screening.paper_download.downloader.time.monotonic", return_value=5.0),
            patch("Screening.paper_download.downloader.time.sleep") as sleep_mock,
        ):
            backoff.wait("example.com")
        sleep_mock.assert_called_once()
        self.assertGreater(sleep_mock.call_args.args[0], 0.0)

    def test_wait_returns_immediately_for_unknown_domain(self) -> None:
        backoff = DomainBackoff()
        with patch("Screening.paper_download.downloader.time.sleep") as sleep_mock:
            backoff.wait("unknown.example")
        sleep_mock.assert_not_called()

    def test_empty_domain_is_noop(self) -> None:
        backoff = DomainBackoff()
        with patch("Screening.paper_download.downloader.time.sleep") as sleep_mock:
            backoff.wait("")
            backoff.on_response("", 429)
        sleep_mock.assert_not_called()
        self.assertEqual(backoff._state, {})

    def test_thread_safety_concurrent_updates(self) -> None:
        backoff = DomainBackoff(jitter=0.0)
        with (
            patch("Screening.paper_download.downloader.time.monotonic", return_value=0.0),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            threads: list[threading.Thread] = []
            for _ in range(10):
                threads.append(threading.Thread(target=backoff.on_response, args=("example.com", 429)))
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        fail_count, _ = backoff._state["example.com"]
        self.assertEqual(fail_count, 10)


class DOIAndPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_detect_publisher_springer(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://link.springer.com/article/10.1007/abc"), "springer")

    def test_detect_publisher_elsevier(self) -> None:
        self.assertEqual(
            self.downloader._detect_publisher("https://www.sciencedirect.com/science/article/pii/S123"), "elsevier"
        )

    def test_detect_publisher_ieee(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://ieeexplore.ieee.org/document/123"), "ieee")

    def test_detect_publisher_wiley(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://onlinelibrary.wiley.com/doi/10.1002/xyz"), "wiley")

    def test_detect_publisher_nature(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://www.nature.com/articles/s41598-020-00000-0"), "nature")

    def test_detect_publisher_plos(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://journals.plos.org/plosone/article?id=10.1371/journal.pone.1"), "plos")

    def test_detect_publisher_sage(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://journals.sagepub.com/doi/10.1177/123"), "sage")

    def test_detect_publisher_taylor(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://www.tandfonline.com/doi/full/10.1080/123"), "taylor")

    def test_detect_publisher_oxford(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://academic.oup.com/journal/article/123"), "oxford")

    def test_detect_publisher_cureus(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://www.cureus.com/articles/12345-test"), "cureus")

    def test_detect_publisher_unknown(self) -> None:
        self.assertEqual(self.downloader._detect_publisher("https://example.test/article/123"), "unknown")

    def test_extract_pii_from_url(self) -> None:
        self.assertEqual(_extract_pii("https://www.sciencedirect.com/science/article/pii/S1234567890"), "S1234567890")

    def test_extract_pii_returns_none_when_absent(self) -> None:
        self.assertIsNone(_extract_pii("https://www.sciencedirect.com/science/article/abs/123"))

    def test_download_paper_rejects_invalid_doi(self) -> None:
        with patch.object(self.downloader, "_request", side_effect=AssertionError("HTTP should not be called")):
            self.assertFalse(self.downloader.download_paper("not-a-doi", output_dir=str(ROOT_DIR / "tmp")))


class DownloadPaperWorkflowTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_download_paper_full_flow_success(self) -> None:
        output_dir = self.tmp_path / "out"
        doi = "10.1000/xyz"
        calls: list[tuple[str, str]] = []

        def fake_request(method: str, url: str, **kwargs):
            calls.append((method, url))
            if method == "HEAD" and url == f"https://doi.org/{doi}":
                return SimpleNamespace(status_code=200, url="https://example.test/paper", text="")
            if method == "GET" and url == "https://example.test/paper":
                return SimpleNamespace(status_code=200, url=url, text='<a href="https://example.test/file.pdf">PDF</a>')
            if method == "GET" and url == "https://example.test/file.pdf":
                return _FakeResponse(
                    status_code=200,
                    headers={"Content-Type": "application/pdf"},
                    chunks=[b"%PDF-1.4\nok\n%%EOF"],
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

        with (
            patch.object(self.downloader, "_request", side_effect=fake_request),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertTrue(self.downloader.download_paper(doi, output_dir=str(output_dir)))

        pdf_path = output_dir / "pdf" / "10.1000_xyz.pdf"
        self.assertTrue(pdf_path.is_file())
        self.assertTrue(self.downloader._is_pdf_file_valid(str(pdf_path)))
        self.assertIn(("HEAD", f"https://doi.org/{doi}"), calls)
        self.assertIn(("GET", "https://example.test/paper"), calls)
        self.assertIn(("GET", "https://example.test/file.pdf"), calls)

    def test_download_paper_unpaywall_fallback(self) -> None:
        output_dir = self.tmp_path / "out"
        doi = "10.1000/xyz"

        def fake_request(method: str, url: str, **kwargs):
            if method == "HEAD" and url == f"https://doi.org/{doi}":
                return SimpleNamespace(status_code=200, url="https://example.test/paper", text="")
            if method == "GET" and url == "https://example.test/paper":
                return SimpleNamespace(status_code=200, url=url, text="<html>No PDF here</html>")
            if method == "GET" and url.startswith("https://api.unpaywall.org/v2/"):
                return _FakeResponse(
                    status_code=200,
                    json_data={"best_oa_location": {"url_for_pdf": "https://oa.test/file.pdf"}},
                )
            if method == "GET" and url == "https://oa.test/file.pdf":
                return _FakeResponse(
                    status_code=200,
                    headers={"Content-Type": "application/pdf"},
                    chunks=[b"%PDF-1.4\nok\n%%EOF"],
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

        with (
            patch.dict(os.environ, {"UNPAYWALL_EMAIL": "a@b.c"}, clear=False),
            patch.object(self.downloader, "_request", side_effect=fake_request),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertTrue(self.downloader.download_paper(doi, output_dir=str(output_dir)))

        pdf_path = output_dir / "pdf" / "10.1000_xyz.pdf"
        self.assertTrue(pdf_path.is_file())

    def test_download_paper_elsevier_api_fallback_writes_xml(self) -> None:
        output_dir = self.tmp_path / "out"
        doi = "10.1000/xyz"

        def fake_request(method: str, url: str, **kwargs):
            if method == "HEAD" and url == f"https://doi.org/{doi}":
                return SimpleNamespace(
                    status_code=200,
                    url="https://www.sciencedirect.com/science/article/pii/S1234567890",
                    text="",
                )
            if method == "GET" and url.startswith("https://api.elsevier.com/content/article/doi/"):
                return _FakeResponse(status_code=200, content=b"<xml>ok</xml>", headers={})
            raise AssertionError(f"Unexpected request: {method} {url}")

        convert_mock = Mock(return_value=True)
        with (
            patch.dict(os.environ, {"ELSEVIER_API_KEY": "k"}, clear=False),
            patch.object(self.downloader, "_request", side_effect=fake_request),
            patch.object(self.downloader, "_get_elsevier_pdf", return_value=None),
            patch.object(self.downloader, "_convert_xml_to_pdf", new=convert_mock),
        ):
            self.assertTrue(self.downloader.download_paper(doi, output_dir=str(output_dir)))

        xml_path = output_dir / "xml" / "10.1000_xyz.xml"
        self.assertTrue(xml_path.is_file())
        convert_mock.assert_called_once()


class ElsevierAPITests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_elsevier_api_missing_key_returns_false_without_http(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.downloader, "_request", side_effect=AssertionError("HTTP should not be called")),
        ):
            self.assertFalse(
                self.downloader._download_elsevier_api(
                    "10.1000/xyz",
                    xml_dir=str(self.tmp_path / "xml"),
                    md_dir=str(self.tmp_path / "md"),
                    pdf_dir=str(self.tmp_path / "pdf"),
                )
            )

    def test_elsevier_api_403_returns_false_and_writes_no_file(self) -> None:
        xml_dir = self.tmp_path / "xml"
        md_dir = self.tmp_path / "md"
        pdf_dir = self.tmp_path / "pdf"
        xml_dir.mkdir()
        md_dir.mkdir()
        pdf_dir.mkdir()

        resp = _FakeResponse(status_code=403, content=b"nope", headers={})
        with (
            patch.dict(os.environ, {"ELSEVIER_API_KEY": "k"}, clear=False),
            patch.object(self.downloader, "_request", return_value=resp),
        ):
            self.assertFalse(
                self.downloader._download_elsevier_api(
                    "10.1000/xyz",
                    xml_dir=str(xml_dir),
                    md_dir=str(md_dir),
                    pdf_dir=str(pdf_dir),
                )
            )
        self.assertEqual(list(xml_dir.glob("*.xml")), [])


class PDFValidationTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def test_valid_pdf(self) -> None:
        path = self.tmp_path / "ok.pdf"
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")
        downloader = ImprovedPaperDownloader()
        self.assertTrue(downloader._is_pdf_file_valid(str(path)))

    def test_empty_file(self) -> None:
        path = self.tmp_path / "empty.pdf"
        path.write_bytes(b"")
        downloader = ImprovedPaperDownloader()
        self.assertFalse(downloader._is_pdf_file_valid(str(path)))

    def test_missing_header(self) -> None:
        path = self.tmp_path / "bad.pdf"
        path.write_bytes(b"NOTPDF\n%%EOF")
        downloader = ImprovedPaperDownloader()
        self.assertFalse(downloader._is_pdf_file_valid(str(path)))

    def test_missing_eof(self) -> None:
        path = self.tmp_path / "noeof.pdf"
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")
        downloader = ImprovedPaperDownloader()
        self.assertFalse(downloader._is_pdf_file_valid(str(path)))

    def test_nonexistent_file(self) -> None:
        downloader = ImprovedPaperDownloader()
        self.assertFalse(downloader._is_pdf_file_valid(str(self.tmp_path / "missing.pdf")))


class PublisherPDFExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_get_springer_pdf_direct_url(self) -> None:
        doi = "10.1007/test"

        def fake_request(method: str, url: str, **kwargs):
            if method == "HEAD" and url.endswith(f"{doi}.pdf"):
                return SimpleNamespace(status_code=200)
            raise AssertionError(f"Unexpected request: {method} {url}")

        with patch.object(self.downloader, "_request", side_effect=fake_request):
            got = self.downloader._get_springer_pdf("https://link.springer.com/article/xyz", doi)
        self.assertEqual(got, f"https://link.springer.com/content/pdf/{doi}.pdf")

    def test_get_springer_pdf_html_fallback(self) -> None:
        doi = "10.1007/test"
        paper_url = "https://link.springer.com/article/10.1007/test"
        html = '<a href="/content/pdf/10.1007/test.pdf">PDF</a>'

        def fake_request(method: str, url: str, **kwargs):
            if method == "HEAD":
                return SimpleNamespace(status_code=404)
            if method == "GET" and url == paper_url:
                return SimpleNamespace(status_code=200, text=html)
            raise AssertionError(f"Unexpected request: {method} {url}")

        with patch.object(self.downloader, "_request", side_effect=fake_request):
            got = self.downloader._get_springer_pdf(paper_url, doi)
        self.assertEqual(got, "https://link.springer.com/content/pdf/10.1007/test.pdf")

    def test_get_elsevier_pdf_citation_meta(self) -> None:
        html = '<meta name="citation_pdf_url" content="https://example.test/paper.pdf" />'
        resp = SimpleNamespace(status_code=200, text=html, url="https://www.sciencedirect.com/science/article/pii/S123")
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_elsevier_pdf("https://www.sciencedirect.com/science/article/pii/S123")
        self.assertEqual(got, "https://example.test/paper.pdf")
        self.assertEqual(self.downloader._elsevier_referer, resp.url)

    def test_get_ieee_pdf_extracts_pdf_url(self) -> None:
        html = 'var x={"pdfUrl":"https://ieee.test/stamp.pdf"};'
        resp = SimpleNamespace(status_code=200, text=html, url="https://ieeexplore.ieee.org/document/1")
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_ieee_pdf("https://ieeexplore.ieee.org/document/1")
        self.assertEqual(got, "https://ieee.test/stamp.pdf")

    def test_get_wiley_pdf_extracts_from_html(self) -> None:
        html = '<a href="/doi/pdf/10.1002/xyz.pdf">Download PDF</a>'
        resp = SimpleNamespace(status_code=200, text=html)
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_wiley_pdf("https://onlinelibrary.wiley.com/doi/10.1002/xyz")
        self.assertEqual(got, "https://onlinelibrary.wiley.com/doi/pdf/10.1002/xyz.pdf")

    def test_get_nature_pdf_extracts_from_html(self) -> None:
        html = '<a data-track-action="download pdf" href="/articles/s41598-020-00000-0.pdf">PDF</a>'
        resp = SimpleNamespace(status_code=200, text=html)
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_nature_pdf("https://www.nature.com/articles/s41598-020-00000-0")
        self.assertEqual(got, "https://www.nature.com/articles/s41598-020-00000-0.pdf")

    def test_get_cureus_pdf_from_article_id(self) -> None:
        paper_url = "https://www.cureus.com/articles/12345-test"
        resp = SimpleNamespace(status_code=200, text="<html>No PDF links</html>")
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_cureus_pdf(paper_url)
        self.assertEqual(got, "https://www.cureus.com/articles/12345.pdf")

    def test_get_generic_pdf_extracts_href(self) -> None:
        html = '<a href="/content/abc.pdf">PDF</a>'
        resp = SimpleNamespace(status_code=200, text=html)
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_generic_pdf("https://example.test/paper")
        self.assertEqual(got, "https://example.test/content/abc.pdf")

    def test_publisher_returns_none_on_no_match(self) -> None:
        resp = SimpleNamespace(status_code=200, text="<html>No links</html>")
        with patch.object(self.downloader, "_request", return_value=resp):
            got = self.downloader._get_generic_pdf("https://example.test/paper")
        self.assertIsNone(got)


class UnpaywallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_returns_best_oa_url(self) -> None:
        data = {"best_oa_location": {"url_for_pdf": "https://oa.test/best.pdf"}}
        with (
            patch.dict(os.environ, {"UNPAYWALL_EMAIL": "a@b.c"}, clear=False),
            patch.object(self.downloader, "_request", return_value=_FakeResponse(status_code=200, json_data=data)),
        ):
            got = self.downloader._get_unpaywall_pdf_url("10.1000/xyz")
        self.assertEqual(got, "https://oa.test/best.pdf")

    def test_falls_back_to_oa_locations(self) -> None:
        data = {"best_oa_location": {}, "oa_locations": [{"url_for_pdf": "https://oa.test/fallback.pdf"}]}
        with (
            patch.dict(os.environ, {"UNPAYWALL_EMAIL": "a@b.c"}, clear=False),
            patch.object(self.downloader, "_request", return_value=_FakeResponse(status_code=200, json_data=data)),
        ):
            got = self.downloader._get_unpaywall_pdf_url("10.1000/xyz")
        self.assertEqual(got, "https://oa.test/fallback.pdf")

    def test_returns_none_without_email(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.downloader, "_request", side_effect=AssertionError("HTTP should not be called")),
        ):
            self.assertIsNone(self.downloader._get_unpaywall_pdf_url("10.1000/xyz"))

    def test_returns_none_on_http_error(self) -> None:
        with (
            patch.dict(os.environ, {"UNPAYWALL_EMAIL": "a@b.c"}, clear=False),
            patch.object(self.downloader, "_request", return_value=_FakeResponse(status_code=404, json_data={})),
        ):
            self.assertIsNone(self.downloader._get_unpaywall_pdf_url("10.1000/xyz"))


class DownloadPDFTests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def setUp(self) -> None:
        self.downloader = ImprovedPaperDownloader()

    def test_saves_valid_pdf(self) -> None:
        pdf_bytes = b"%PDF-1.4\nhello\n%%EOF"
        resp = _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[pdf_bytes],
        )
        with patch.object(self.downloader, "_request", return_value=resp):
            ok = self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path))
        self.assertTrue(ok)
        saved = self.tmp_path / "10.1000_xyz.pdf"
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), pdf_bytes)

    def test_raises_permission_error_on_401(self) -> None:
        resp = _FakeResponse(status_code=401, headers={"Content-Type": "application/pdf"}, chunks=[b""])
        with patch.object(self.downloader, "_request", return_value=resp):
            with self.assertRaises(PermissionError):
                self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path))

    def test_raises_permission_error_on_403(self) -> None:
        resp = _FakeResponse(status_code=403, headers={"Content-Type": "application/pdf"}, chunks=[b""])
        with patch.object(self.downloader, "_request", return_value=resp):
            with self.assertRaises(PermissionError):
                self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path))

    def test_retries_on_server_error(self) -> None:
        ok_resp = _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF-1.4\nok\n%%EOF"],
        )
        responses = [
            _FakeResponse(status_code=500, headers={"Content-Type": "text/html"}, chunks=[]),
            _FakeResponse(status_code=500, headers={"Content-Type": "text/html"}, chunks=[]),
            ok_resp,
        ]
        with (
            patch.object(self.downloader, "_request", side_effect=responses),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertTrue(self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path)))

    def test_fails_after_max_attempts(self) -> None:
        resp = _FakeResponse(status_code=500, headers={"Content-Type": "text/html"}, chunks=[])
        with (
            patch.object(self.downloader, "_request", return_value=resp),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertFalse(
                self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path))
            )

    def test_non_pdf_response_200_is_skipped_and_writes_no_file(self) -> None:
        resp = _FakeResponse(
            status_code=200,
            headers={"Content-Type": "text/html"},
            chunks=[b"<html>not a pdf</html>"],
        )
        with (
            patch.object(self.downloader, "_request", return_value=resp),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertFalse(self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path)))
        self.assertFalse((self.tmp_path / "10.1000_xyz.pdf").exists())

    def test_corrupted_download_is_cleaned_up(self) -> None:
        resp = _FakeResponse(
            status_code=200,
            headers={"Content-Type": "application/pdf"},
            chunks=[b"%PDF-1.4\nincomplete\n"],
        )
        with (
            patch.object(self.downloader, "_request", return_value=resp),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertFalse(self.downloader._download_pdf("https://example.test/file.pdf", "10.1000/xyz", str(self.tmp_path)))
        self.assertFalse((self.tmp_path / "10.1000_xyz.pdf").exists())

    def test_skips_existing_valid_pdf(self) -> None:
        output_dir = self.tmp_path / "out"
        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True)
        doi = "10.1000/xyz"
        existing = pdf_dir / "10.1000_xyz.pdf"
        existing.write_bytes(b"%PDF-1.4\nok\n%%EOF")

        with patch.object(self.downloader, "_request", side_effect=AssertionError("HTTP should not be called")):
            self.assertTrue(self.downloader.download_paper(doi, output_dir=str(output_dir)))

    def test_redownloads_corrupted_pdf(self) -> None:
        output_dir = self.tmp_path / "out"
        pdf_dir = output_dir / "pdf"
        pdf_dir.mkdir(parents=True)
        doi = "10.1000/xyz"
        existing = pdf_dir / "10.1000_xyz.pdf"
        existing.write_bytes(b"NOTPDF")

        calls: list[tuple[str, str]] = []

        def fake_request(method: str, url: str, **kwargs):
            calls.append((method, url))
            if method == "HEAD" and url == f"https://doi.org/{doi}":
                return SimpleNamespace(status_code=200, url="https://example.test/paper", text="")
            if method == "GET" and url == "https://example.test/paper":
                return SimpleNamespace(status_code=200, url=url, text='<a href="https://example.test/file.pdf">PDF</a>')
            if method == "GET" and url == "https://example.test/file.pdf":
                return _FakeResponse(
                    status_code=200,
                    headers={"Content-Type": "application/pdf"},
                    chunks=[b"%PDF-1.4\nok\n%%EOF"],
                )
            raise AssertionError(f"Unexpected request: {method} {url}")

        with (
            patch.object(self.downloader, "_request", side_effect=fake_request),
            patch("Screening.paper_download.downloader.time.sleep"),
            patch("Screening.paper_download.downloader.random.uniform", return_value=0.0),
        ):
            self.assertTrue(self.downloader.download_paper(doi, output_dir=str(output_dir)))
        self.assertTrue((pdf_dir / "10.1000_xyz.pdf").is_file())
        self.assertIn(("GET", "https://example.test/file.pdf"), calls)


class CLITests(unittest.TestCase):
    @pytest.fixture(autouse=True)
    def _tmp(self, tmp_path: Path):
        self.tmp_path = tmp_path

    def test_read_dois_from_file_normal(self) -> None:
        doi_file = self.tmp_path / "doi.txt"
        doi_file.write_text("10.1/abc\n10.2/def\n", encoding="utf-8")
        self.assertEqual(_read_dois_from_file(doi_file), ["10.1/abc", "10.2/def"])

    def test_read_dois_skips_comments_and_blanks(self) -> None:
        doi_file = self.tmp_path / "doi.txt"
        doi_file.write_text("\n# comment\n10.1/abc\n\n# another\n10.2/def\n", encoding="utf-8")
        self.assertEqual(_read_dois_from_file(doi_file), ["10.1/abc", "10.2/def"])

    def test_dedupe_preserve_order(self) -> None:
        self.assertEqual(_dedupe_preserve_order(["a", "b", "a", "c", "b"]), ["a", "b", "c"])

    def test_dedupe_empty_list(self) -> None:
        self.assertEqual(_dedupe_preserve_order([]), [])

    def test_cli_parallel_downloads_calls_all_dois_and_reuses_backoff(self) -> None:
        doi_file = self.tmp_path / "dois.txt"
        doi_file.write_text("10.1/a\n10.2/b\n10.3/c\n", encoding="utf-8")

        calls: list[str] = []
        created_backoffs: list[object] = []

        class _FakeDownloader:
            def __init__(self, *args, **kwargs) -> None:
                created_backoffs.append(kwargs.get("backoff"))

            def download_paper(self, doi: str, *, output_dir: str = "downloads", **kwargs) -> bool:
                calls.append(doi)
                return True

        shared_backoff = object()
        with (
            patch.object(paper_cli, "DomainBackoff", return_value=shared_backoff),
            patch.object(paper_cli, "ImprovedPaperDownloader", _FakeDownloader),
        ):
            rc = paper_cli.main(["--doi-file", str(doi_file), "--output-dir", str(self.tmp_path / "out"), "--workers", "3"])

        self.assertEqual(rc, 0)
        self.assertEqual(sorted(calls), ["10.1/a", "10.2/b", "10.3/c"])
        self.assertTrue(created_backoffs)
        self.assertEqual({id(x) for x in created_backoffs}, {id(shared_backoff)})

    def test_cli_one_doi_fails_others_continue(self) -> None:
        doi_file = self.tmp_path / "dois.txt"
        doi_file.write_text("10.1/a\n10.2/b\n10.3/c\n", encoding="utf-8")

        calls: list[str] = []
        outcomes = {"10.1/a": False, "10.2/b": True, "10.3/c": True}

        class _FakeDownloader:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def download_paper(self, doi: str, *, output_dir: str = "downloads", **kwargs) -> bool:
                calls.append(doi)
                return outcomes[doi]

        with patch.object(paper_cli, "ImprovedPaperDownloader", _FakeDownloader):
            rc = paper_cli.main(["--doi-file", str(doi_file), "--output-dir", str(self.tmp_path / "out"), "--workers", "3"])

        self.assertEqual(rc, 0)
        self.assertEqual(sorted(calls), ["10.1/a", "10.2/b", "10.3/c"])


if __name__ == "__main__":
    unittest.main()
