"""
Improved Research Paper Downloader with Better PDF Detection.

Implementation module (SRP split). CLI entrypoint: `python -m Screening.paper_download`.
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
    with _print_lock:
        print(*args, **kwargs)


def safe_print_block(*lines: str):
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
    match = re.search(r"/pii/([A-Z0-9]+)", url, re.IGNORECASE)
    return match.group(1) if match else None


class DomainBackoff:
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
        if not domain:
            return

        with self._lock:
            _, next_allowed = self._state.get(domain, (0, 0.0))

        now = time.monotonic()
        if now < next_allowed:
            time.sleep(next_allowed - now)

    def on_response(self, domain: str, status_code: int) -> None:
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
    def __init__(
        self,
        *,
        backoff: DomainBackoff | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
    ):
        if _HAS_CURL_CFFI and curl_requests is not None:
            self.session = curl_requests.Session(impersonate="chrome124")
            self._using_curl_cffi = True
        else:
            self.session = requests.Session()
            self._using_curl_cffi = False
            self.session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
                    "Sec-Ch-Ua-Mobile": "?0",
                    "Sec-Ch-Ua-Platform": '"Windows"',
                }
            )

        self._backoff = backoff
        self._timeout = timeout
        self._elsevier_referer: str | None = None

    def _request(self, method: str, url: str, **kwargs) -> Any:
        domain = urlparse(url).netloc.lower()
        if self._backoff and domain:
            self._backoff.wait(domain)

        kwargs.setdefault("timeout", self._timeout)
        response = self.session.request(method, url, **kwargs)  # type: ignore[arg-type]

        if self._backoff and domain:
            self._backoff.on_response(domain, response.status_code)

        return response

    def _handle_no_pdf(self, paper_url: str) -> None:
        safe_print_block(
            "ERROR: Could not find PDF link",
            f"   Try visiting this URL in your browser: {paper_url}",
        )

    def _is_pdf_file_valid(self, path: str, eof_tail_bytes: int = 8192) -> bool:
        try:
            p = Path(path)
            if not p.is_file():
                return False

            size = p.stat().st_size
            if size <= 0:
                return False

            with open(p, "rb") as f:
                head = f.read(16)
                if not head.startswith(b"%PDF"):
                    return False

                tail_len = min(size, int(eof_tail_bytes))
                if tail_len <= 0:
                    return False

                f.seek(-tail_len, os.SEEK_END)
                tail = f.read(tail_len)

            return b"%%EOF" in tail
        except Exception:
            return False

    def download_paper(self, doi, output_dir="downloads"):
        doi = doi.strip()
        if not doi.startswith("10."):
            match = re.search(r"10\.\d{4,}/[^\s]+", doi)
            if match:
                doi = match.group(0)
            else:
                safe_print(f"Invalid DOI format: {doi}")
                return False

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        pdf_dir = os.path.join(output_dir, "pdf")
        xml_dir = os.path.join(output_dir, "xml")
        md_dir = os.path.join(output_dir, "md")
        Path(pdf_dir).mkdir(parents=True, exist_ok=True)
        Path(xml_dir).mkdir(parents=True, exist_ok=True)
        Path(md_dir).mkdir(parents=True, exist_ok=True)

        base_name = doi.replace("/", "_")
        ext_dir_map = {".pdf": pdf_dir, ".xml": xml_dir, ".json": xml_dir}
        for ext, sub_dir in ext_dir_map.items():
            existing_path = os.path.join(sub_dir, base_name + ext)
            if not os.path.exists(existing_path):
                continue

            if ext == ".pdf":
                if self._is_pdf_file_valid(existing_path):
                    safe_print(f"SKIP: Already exists, skipping: {existing_path}")
                    return True
                safe_print(f"Existing PDF looks corrupted, re-downloading: {existing_path}")
                try:
                    os.remove(existing_path)
                except Exception as e:
                    safe_print(f"ERROR: Could not remove existing file: {e}")
                    return False
            else:
                if os.path.getsize(existing_path) > 0:
                    safe_print(f"SKIP: Already exists, skipping: {existing_path}")
                    return True
                safe_print(f"Existing {ext} file is empty, re-downloading: {existing_path}")
                try:
                    os.remove(existing_path)
                except Exception as e:
                    safe_print(f"ERROR: Could not remove existing file: {e}")
                    return False

        doi_url = f"https://doi.org/{doi}"
        try:
            response = self._request("HEAD", doi_url, allow_redirects=True)
            if response.status_code >= 400:
                response = self._request("GET", doi_url, allow_redirects=True)
            paper_url = response.url
        except Exception as e:
            safe_print(f"Error resolving DOI: {e}")
            return False

        publisher = self._detect_publisher(paper_url)

        safe_print_block(
            f"\nProcessing DOI: {doi}",
            f"  Paper URL: {paper_url}",
            f"  Detected publisher: {publisher}",
        )

        pdf_url = self._get_pdf_url_by_publisher(paper_url, publisher, doi)

        if not pdf_url:
            pdf_url = self._get_unpaywall_pdf_url(doi)

        if pdf_url:
            pdf_downloaded = False
            try:
                pdf_downloaded = self._download_pdf(pdf_url, doi, pdf_dir)
            except PermissionError:
                safe_print(f"ERROR: Permission denied (HTTP 403/401) for {doi}")

            if pdf_downloaded:
                return True

        if publisher == "elsevier":
            xml_ok = self._download_elsevier_api(doi, xml_dir, md_dir, pdf_dir)
            if xml_ok:
                return True

        if pdf_url is None:
            pass
        elif not pdf_downloaded:
            unpaywall_url = self._get_unpaywall_pdf_url(doi)
            if unpaywall_url and unpaywall_url != pdf_url:
                safe_print(f"  Trying Unpaywall alternative: {unpaywall_url}")
                try:
                    if self._download_pdf(unpaywall_url, doi, pdf_dir):
                        return True
                except PermissionError:
                    pass

        self._handle_no_pdf(paper_url)
        return False

    def _detect_publisher(self, url):
        domain = urlparse(url).netloc.lower()

        if "springer" in domain or "link.springer.com" in domain:
            return "springer"
        elif "sciencedirect" in domain or "elsevier" in domain:
            return "elsevier"
        elif "ieee" in domain:
            return "ieee"
        elif "wiley" in domain:
            return "wiley"
        elif "nature.com" in domain:
            return "nature"
        elif "science.org" in domain or "sciencemag.org" in domain:
            return "science"
        elif "oup.com" in domain or "oxford" in domain:
            return "oxford"
        elif "plos.org" in domain:
            return "plos"
        elif "journals.sagepub.com" in domain:
            return "sage"
        elif "tandfonline.com" in domain:
            return "taylor"
        elif "cureus.com" in domain:
            return "cureus"
        else:
            return "unknown"

    def _get_pdf_url_by_publisher(self, paper_url, publisher, doi):
        if publisher == "springer":
            return self._get_springer_pdf(paper_url, doi)
        elif publisher == "elsevier":
            return self._get_elsevier_pdf(paper_url)
        elif publisher == "ieee":
            return self._get_ieee_pdf(paper_url)
        elif publisher == "wiley":
            return self._get_wiley_pdf(paper_url)
        elif publisher == "nature":
            return self._get_nature_pdf(paper_url)
        elif publisher == "cureus":
            return self._get_cureus_pdf(paper_url)
        else:
            return self._get_generic_pdf(paper_url)

    def _get_springer_pdf(self, paper_url, doi):
        pdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
        safe_print(f"  Trying Springer PDF URL: {pdf_url}")

        response = self._request("HEAD", pdf_url, allow_redirects=True)
        if response.status_code == 200:
            return pdf_url

        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="(/content/pdf/[^"]+\.pdf)"',
                r'href="(https://link\.springer\.com/content/pdf/[^"]+\.pdf)"',
                r'data-article-pdf="([^"]+)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except Exception:
            pass

        return None

    def _get_elsevier_pdf(self, paper_url):
        article_url = paper_url
        content = ""

        pii = _extract_pii(paper_url)
        if pii and "linkinghub" in paper_url:
            article_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
            safe_print(f"  Resolved linkinghub -> {article_url}")
        else:
            article_url = paper_url

        try:
            response = self._request("GET", article_url)
            article_url = response.url
            content = response.text
            safe_print(f"  Elsevier article URL: {article_url}")

            if response.status_code >= 400 or "there was a problem" in content.lower():
                safe_print(f"  Warning: article page returned error (status {response.status_code})")
                content = ""
        except Exception as e:
            safe_print(f"  Elsevier page fetch failed: {e}")

        if content:
            meta_match = re.search(
                r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
                content,
                re.IGNORECASE,
            )
            if meta_match:
                pdf_url = meta_match.group(1)
                self._elsevier_referer = article_url
                safe_print(f"  Found citation_pdf_url: {pdf_url}")
                return pdf_url

            patterns = [
                r'pdfurl":"([^"]+)"',
                r'href="([^"]*pdfft[^"]*)"',
                r'href="([^"]*/pdf/download[^"]*)"',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace("\\/", "/")
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(article_url, pdf_url)
                    self._elsevier_referer = article_url
                    return pdf_url

        for candidate_url in (article_url, paper_url):
            pii_match = re.search(r"/pii/([A-Z0-9]+)", candidate_url, re.IGNORECASE)
            if pii_match:
                pii = pii_match.group(1)
                parsed = urlparse(article_url)
                if "sciencedirect.com" in parsed.netloc:
                    base = f"{parsed.scheme}://{parsed.netloc}"
                else:
                    base = "https://www.sciencedirect.com"
                self._elsevier_referer = f"{base}/science/article/pii/{pii}"
                pdfft = f"{base}/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true"
                safe_print(f"  Constructed pdfft fallback: {pdfft}")
                return pdfft

        return None

    def _get_ieee_pdf(self, paper_url):
        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="([^"]+\.pdf)"',
                r'pdfUrl":"([^"]+)"',
                r"xpl\/articleDetails\.jsp\?arnumber=(\d+)",
            ]

            for pattern in patterns[:2]:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url

            match = re.search(patterns[2], content)
            if match:
                arnumber = match.group(1)
                return f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}"

        except Exception as e:
            safe_print(f"  IEEE PDF lookup error: {e}")

        return None

    def _get_wiley_pdf(self, paper_url):
        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="([^"]+\.pdf)"',
                r'pdfLink":"([^"]+)"',
                r'"pdfUrl":"([^"]+)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace("\\/", "/")
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url

        except Exception as e:
            safe_print(f"  Wiley PDF lookup error: {e}")

        return None

    def _get_nature_pdf(self, paper_url):
        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="([^"]+\.pdf)"',
                r'href="([^"]+/pdf/[^"]+)"',
                r'data-track-action="download pdf"\s+href="([^"]+)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url

        except Exception as e:
            safe_print(f"  Nature PDF lookup error: {e}")

        return None

    def _get_cureus_pdf(self, paper_url):
        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="([^"]*download[^"]*pdf[^"]*)"',
                r'href="([^"]*\.pdf[^"]*)"',
                r'data-download-url="([^"]+)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url

            parsed = urlparse(paper_url)
            path = parsed.path
            match = re.search(r"/articles/(\d+)", path)
            if match:
                article_id = match.group(1)
                pdf_url = f"{parsed.scheme}://{parsed.netloc}/articles/{article_id}.pdf"
                return pdf_url

        except Exception as e:
            safe_print(f"  Cureus PDF lookup error: {e}")

        return None

    def _get_unpaywall_pdf_url(self, doi: str) -> str | None:
        email = os.getenv("UNPAYWALL_EMAIL")
        if not email:
            return None

        url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(email)}"
        try:
            response = self._request("GET", url)
            if response.status_code != 200:
                return None
            data = response.json()

            best = data.get("best_oa_location") or {}
            for k in ("url_for_pdf", "url"):
                v = best.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return v

            for loc in data.get("oa_locations") or []:
                if not isinstance(loc, dict):
                    continue
                for k in ("url_for_pdf", "url"):
                    v = loc.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        return v
        except Exception:
            return None

        return None

    def _get_generic_pdf(self, paper_url):
        try:
            response = self._request("GET", paper_url)
            content = response.text

            patterns = [
                r'href="([^"]+\.pdf)"',
                r'pdfUrl":"([^"]+)"',
                r'href="([^"]*download[^"]*\.pdf[^"]*)"',
            ]

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace("\\/", "/")
                    if not pdf_url.startswith("http"):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url

        except Exception as e:
            safe_print(f"  Generic PDF lookup error: {e}")

        return None

    def _download_pdf(self, pdf_url, doi, output_dir):
        base_name = doi.replace("/", "_")
        pdf_path = os.path.join(output_dir, base_name + ".pdf")

        headers = {
            "User-Agent": self.session.headers.get("User-Agent", ""),
            "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self._elsevier_referer and ("sciencedirect" in pdf_url or "elsevier" in pdf_url):
            headers["Referer"] = self._elsevier_referer

        max_attempts = 3

        for attempt in range(1, max_attempts + 1):
            try:
                safe_print(f"  Downloading PDF: {pdf_url} (attempt {attempt}/{max_attempts})")
                response = self._request(
                    "GET",
                    pdf_url,
                    headers=headers,
                    stream=True,
                    allow_redirects=True,
                )

                if response.status_code in (401, 403):
                    raise PermissionError(f"HTTP {response.status_code}")

                if response.status_code != 200:
                    safe_print(f"  ERROR: HTTP {response.status_code} for PDF download")
                    continue

                content_type = response.headers.get("Content-Type", "").lower()
                if "pdf" not in content_type and "application/octet-stream" not in content_type:
                    try:
                        chunk = next(response.iter_content(chunk_size=4096))
                    except StopIteration:
                        safe_print("  ERROR: Empty response content")
                        continue
                    if not chunk.startswith(b"%PDF"):
                        safe_print(f"  ERROR: Non-PDF response (Content-Type: {content_type})")
                        continue

                    with open(pdf_path, "wb") as f:
                        f.write(chunk)
                        for data in response.iter_content(chunk_size=8192):
                            if data:
                                f.write(data)
                else:
                    with open(pdf_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)

                if self._is_pdf_file_valid(pdf_path):
                    safe_print(f"  SUCCESS: PDF saved to {pdf_path}")
                    return True

                safe_print("  ERROR: Downloaded PDF appears corrupted; retrying...")
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

            except PermissionError:
                raise
            except Exception as e:
                safe_print(f"  ERROR: Download failed on attempt {attempt}: {e}")

            time.sleep(1.0 + random.uniform(0.0, 0.5))

        safe_print(f"  ERROR: Download failed after {max_attempts} attempts: {doi}")
        return False

    def _convert_xml_to_pdf(self, xml_path: str, md_dir: str, pdf_dir: str) -> bool:
        try:
            info = parse_xml(Path(xml_path))
            md_text = build_md(info)
        except Exception as e:
            safe_print(f"  XML parse/build failed: {e}")
            return False

        base_name = Path(xml_path).stem
        md_path = os.path.join(md_dir, base_name + ".md")
        pdf_path = os.path.join(pdf_dir, base_name + ".pdf")

        try:
            Path(md_path).write_text(md_text, encoding="utf-8")
            safe_print(f"  OK: Markdown generated: {md_path}")
        except Exception as e:
            safe_print(f"  Failed to write Markdown: {e}")
            return False

        try:
            convert_md_to_pdf(Path(md_path), Path(pdf_path))
            safe_print(f"  OK: PDF generated from XML: {pdf_path}")
            return True
        except Exception as e:
            safe_print(f"  Failed to convert Markdown to PDF: {e}")
            return False

    def _download_elsevier_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        api_key = os.getenv("ELSEVIER_API_KEY")
        if not api_key:
            safe_print("  Elsevier API key missing: set ELSEVIER_API_KEY in Screening/.env")
            return False

        url = f"https://api.elsevier.com/content/article/doi/{quote(doi)}"
        headers = {
            "X-ELS-APIKey": api_key,
            "Accept": "text/xml",
        }

        try:
            response = self._request("GET", url, headers=headers)
        except Exception as e:
            safe_print(f"  Elsevier API request error: {e}")
            return False

        status_code = int(getattr(response, "status_code", 0) or 0)

        if status_code == 200:
            content = response.content
            if not content:
                safe_print("  Elsevier API returned empty content")
                return False
            filepath = os.path.join(xml_dir, doi.replace("/", "_") + ".xml")
            try:
                with open(filepath, "wb") as f:
                    f.write(content)
                safe_print(f"  OK: Elsevier XML downloaded: {filepath}")
                self._convert_xml_to_pdf(filepath, md_dir, pdf_dir)
                return True
            except Exception as e:
                safe_print(f"  Failed to save Elsevier XML: {e}")
                return False

        if status_code in (401, 403):
            safe_print(f"  Elsevier API auth/permission error (HTTP {status_code}) for DOI {doi}")
            return False

        if status_code == 404:
            safe_print(f"  Elsevier API: DOI not found or not open-access (HTTP 404): {doi}")
            return False

        if status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
            safe_print(f"  Elsevier API rate limited (HTTP 429), X-RateLimit-Remaining={remaining}")
            return False

        safe_print(f"  Elsevier API request failed (HTTP {status_code})")
        return False

    def _download_wiley_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        """Fallback: download Wiley full-text XML via TDM API.

        Requires WILEY_TDM_TOKEN in Screening/.env.
        """
        token = os.getenv("WILEY_TDM_TOKEN")
        if not token:
            safe_print("  Wiley token missing: set WILEY_TDM_TOKEN in Screening/.env")
            return False

        url = "https://api.wiley.com/onlinelibrary/tdm/v1/articles"
        headers = {
            "Wiley-TDM-Client-Token": token,
            "Accept": "application/xml",
        }
        params = {"doi": doi}

        try:
            response = self._request("GET", url, headers=headers, params=params)
        except Exception as e:
            safe_print(f"  Wiley API request error: {e}")
            return False

        status_code = int(getattr(response, "status_code", 0) or 0)

        if status_code == 200:
            content = response.content
            if not content:
                safe_print("  Wiley API returned empty content")
                return False
            filepath = os.path.join(xml_dir, doi.replace("/", "_") + ".xml")
            try:
                with open(filepath, "wb") as f:
                    f.write(content)
                safe_print(f"  OK: Wiley XML downloaded: {filepath}")
                self._convert_xml_to_pdf(filepath, md_dir, pdf_dir)
                return True
            except Exception as e:
                safe_print(f"  Failed to save Wiley XML: {e}")
                return False

        if status_code in (401, 403):
            safe_print(f"  Wiley API auth/permission error (HTTP {status_code}) for DOI {doi}")
            return False

        if status_code == 404:
            safe_print(f"  Wiley API: DOI not found or not open-access (HTTP 404): {doi}")
            return False

        if status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
            safe_print(f"  Wiley API rate limited (HTTP 429), X-RateLimit-Remaining={remaining}")
            return False

        safe_print(f"  Wiley API request failed (HTTP {status_code})")
        return False

    def _download_springer_nature_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        """Fallback: download Springer/Nature full-text XML via Springer Nature API.

        Requires SPRINGER_NATURE_API_KEY in Screening/.env.
        """
        api_key = os.getenv("SPRINGER_NATURE_API_KEY")
        if not api_key:
            safe_print("  Springer Nature API key missing: set SPRINGER_NATURE_API_KEY in Screening/.env")
            return False

        url = f"https://api.springernature.com/meta/v2/xml?q=doi:{quote(doi)}&api_key={quote(api_key)}"
        headers = {"Accept": "application/xml"}

        try:
            response = self._request("GET", url, headers=headers)
        except Exception as e:
            safe_print(f"  Springer Nature API request error: {e}")
            return False

        status_code = int(getattr(response, "status_code", 0) or 0)

        filepath = os.path.join(xml_dir, doi.replace("/", "_") + ".xml")

        if status_code == 200:
            content = response.content
            if not content:
                safe_print("  Springer Nature API returned empty content")
                return False
            try:
                with open(filepath, "wb") as f:
                    f.write(content)
                safe_print(f"  OK: Springer/Nature XML downloaded: {filepath}")
                self._convert_xml_to_pdf(filepath, md_dir, pdf_dir)
                return True
            except Exception as e:
                safe_print(f"  Failed to save Springer/Nature XML: {e}")
                return False

        if status_code in (401, 403):
            safe_print(f"  Springer Nature API auth/permission error (HTTP {status_code}) for DOI {doi}")
            return False

        if status_code == 404:
            safe_print(f"  Springer Nature API: DOI not found or not open-access (HTTP 404): {doi}")
            return False

        if status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
            safe_print(f"  Springer Nature API rate limited (HTTP 429), X-RateLimit-Remaining={remaining}")
            return False

        safe_print(f"  Springer Nature API request failed (HTTP {status_code})")
        return False
