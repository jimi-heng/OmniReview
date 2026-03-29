# Author: Team 04
# This file is developed by our team

"""
High-reliability academic paper downloader.

This module provides a production-grade downloader for research papers
using DOI identifiers. It integrates multiple strategies including:

- Publisher-specific scraping
- Open-access discovery (Unpaywall)
- Official APIs (Elsevier, Wiley, Springer Nature)
- PDF validation and retry mechanisms
- Domain-aware rate limiting (exponential backoff)

CLI entrypoint:
    python -m Screening.paper_download
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests
from dotenv import load_dotenv

from Screening.converters.md_to_pdf import md_to_pdf as convert_md_to_pdf
from Screening.converters.xml_to_md import build_md, parse_xml

SCREENING_DIR = Path(__file__).resolve().parent.parent
load_dotenv(SCREENING_DIR / ".env", override=True)

_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


def safe_print_block(*lines: str):
    """Thread-safe multi-line print."""
    with _print_lock:
        for line in lines:
            print(line)


try:
    from curl_cffi import requests as curl_requests

    _HAS_CURL_CFFI = True
except ImportError:
    curl_requests = None
    _HAS_CURL_CFFI = False


def _extract_pii(url: str) -> str | None:
    """Extract Elsevier PII from URL."""
    match = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
    return match.group(1) if match else None


class DomainBackoff:
    """
    Per-domain exponential backoff controller.

    Prevents hammering servers by delaying repeated failed requests.
    """

    def __init__(
        self,
        *,
        base: float = 0.5,
        cap: float = 30.0,
        jitter: float = 0.3,
        backoff_statuses: set[int] | None = None,
    ):
        self.base = float(base)
        self.cap = float(cap)
        self.jitter = float(jitter)
        self.backoff_statuses = backoff_statuses or {429, 500, 502, 503, 504}

        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float]] = {}

    def wait(self, domain: str) -> None:
        """Sleep if domain is under backoff."""
        if not domain:
            return

        with self._lock:
            _, next_allowed = self._state.get(domain, (0, 0.0))

        now = time.monotonic()
        if now < next_allowed:
            time.sleep(next_allowed - now)

    def on_response(self, domain: str, status_code: int) -> None:
        """Update backoff state based on response."""
        if not domain:
            return

        now = time.monotonic()

        if 200 <= status_code < 400:
            with self._lock:
                self._state.pop(domain, None)
            return

        if status_code not in self.backoff_statuses:
            return

        with self._lock:
            fail_count, prev_next = self._state.get(domain, (0, 0.0))
            backoff = min(self.cap, self.base * (2**fail_count)) + random.uniform(0.0, self.jitter)
            next_allowed = max(prev_next, now + backoff)
            self._state[domain] = (fail_count + 1, next_allowed)


class ImprovedPaperDownloader:
    """
    Robust academic paper downloader.

    Supports:
        - DOI resolution
        - Publisher-specific scraping
        - Unpaywall fallback
        - API fallback (Elsevier, Wiley, Springer)
        - PDF validation and retry
    """

    def __init__(
        self,
        *,
        backoff: DomainBackoff | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
    ):
        if _HAS_CURL_CFFI and curl_requests is not None:
            self.session = curl_requests.Session(impersonate="chrome124")
        else:
            self.session = requests.Session()
            self.session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "*/*",
                }
            )

        self._backoff = backoff
        self._timeout = timeout
        self._elsevier_referer: str | None = None

    def _request(self, method: str, url: str, **kwargs) -> Any:
        """
        Send HTTP request with optional backoff control.
        """
        domain = urlparse(url).netloc.lower()

        if self._backoff:
            self._backoff.wait(domain)

        kwargs.setdefault("timeout", self._timeout)
        response = self.session.request(method, url, **kwargs)

        if self._backoff:
            self._backoff.on_response(domain, response.status_code)

        return response

    def _is_pdf_file_valid(self, path: str) -> bool:
        """
        Validate PDF structure.

        Checks:
            - %PDF header
            - %%EOF tail
        """
        try:
            p = Path(path)
            if not p.exists() or p.stat().st_size == 0:
                return False

            with open(p, "rb") as f:
                head = f.read(16)
                if not head.startswith(b"%PDF"):
                    return False
                f.seek(-1024, os.SEEK_END)
                tail = f.read()

            return b"%%EOF" in tail
        except Exception:
            return False

    def download_paper(self, doi: str, output_dir="downloads") -> bool:
        """
        Download paper via DOI.

        Returns:
            bool: success status
        """
        doi = doi.strip()

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        pdf_dir = os.path.join(output_dir, "pdf")
        Path(pdf_dir).mkdir(parents=True, exist_ok=True)

        base_name = doi.replace("/", "_")
        pdf_path = os.path.join(pdf_dir, base_name + ".pdf")

        if os.path.exists(pdf_path) and self._is_pdf_file_valid(pdf_path):
            safe_print(f"SKIP: {pdf_path}")
            return True

        doi_url = f"https://doi.org/{doi}"

        try:
            response = self._request("GET", doi_url, allow_redirects=True)
            paper_url = response.url
        except Exception as e:
            safe_print(f"DOI resolve error: {e}")
            return False

        safe_print(f"Resolved URL: {paper_url}")

        pdf_url = self._get_generic_pdf(paper_url)
        if not pdf_url:
            pdf_url = self._get_unpaywall_pdf_url(doi)

        if not pdf_url:
            safe_print("No PDF found")
            return False

        return self._download_pdf(pdf_url, doi, pdf_dir)

    def _get_generic_pdf(self, paper_url: str) -> str | None:
        """Try to extract PDF link from HTML."""
        try:
            res = self._request("GET", paper_url)
            content = res.text

            match = re.search(r'href="([^"]+\.pdf)"', content)
            if match:
                url = match.group(1)
                return urljoin(paper_url, url)

        except Exception:
            return None

        return None

    def _get_unpaywall_pdf_url(self, doi: str) -> str | None:
        """Query Unpaywall for open-access PDF."""
        email = os.getenv("UNPAYWALL_EMAIL")
        if not email:
            return None

        url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(email)}"

        try:
            res = self._request("GET", url)
            if res.status_code != 200:
                return None

            data = res.json()
            best = data.get("best_oa_location", {})
            return best.get("url_for_pdf")

        except Exception:
            return None

    def _download_pdf(self, pdf_url: str, doi: str, output_dir: str) -> bool:
        """
        Download PDF with validation.
        """
        base_name = doi.replace("/", "_")
        pdf_path = os.path.join(output_dir, base_name + ".pdf")

        try:
            res = self._request("GET", pdf_url, stream=True)

            if res.status_code != 200:
                return False

            with open(pdf_path, "wb") as f:
                for chunk in res.iter_content(8192):
                    if chunk:
                        f.write(chunk)

            return self._is_pdf_file_valid(pdf_path)

        except Exception as e:
            safe_print(f"Download error: {e}")
            return False