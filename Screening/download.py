"""
Improved Research Paper Downloader with Better PDF Detection
Handles Springer, Elsevier, IEEE, Wiley, and other major publishers
"""

import argparse
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import re
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse
import time
from dotenv import load_dotenv
from xml_to_md import parse_xml, build_md
from md_to_pdf import md_to_pdf as convert_md_to_pdf

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

# Global lock for thread-safe console output
_print_lock = threading.Lock()


def safe_print(*args, **kwargs):
    """Thread-safe print: ensures each line is output atomically."""
    with _print_lock:
        print(*args, **kwargs)


def safe_print_block(*lines: str):
    """Print multiple lines atomically so they are not interleaved."""
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
    """Extract Elsevier PII from a URL (e.g. linkinghub or sciencedirect)."""
    match = re.search(r'/pii/([A-Z0-9]+)', url, re.IGNORECASE)
    return match.group(1) if match else None


class DomainBackoff:
    """
    Thread-safe, per-domain adaptive backoff.

    - No sleeping by default.
    - If a domain returns 429/5xx, apply exponential backoff + jitter shared by all threads.
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
        # domain -> (fail_count, next_allowed_time_monotonic)
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

        # Reset on success-ish responses (including redirects)
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
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Sec-Ch-Ua': '"Chromium";v="131", "Not_A Brand";v="24"',
                'Sec-Ch-Ua-Mobile': '?0',
                'Sec-Ch-Ua-Platform': '"Windows"',
            })

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
        """Lightweight PDF validation: must start with %PDF and contain %%EOF near the end.

        This catches common truncation cases (e.g. only the first chunk saved, missing trailer).
        """
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
        """Download a paper given its DOI with improved publisher handling."""
        # Clean DOI
        doi = doi.strip()
        if not doi.startswith('10.'):
            match = re.search(r'10\.\d{4,}/[^\s]+', doi)
            if match:
                doi = match.group(0)
            else:
                safe_print(f"Invalid DOI format: {doi}")
                return False

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Create subdirectories for different file types
        pdf_dir = os.path.join(output_dir, "pdf")
        xml_dir = os.path.join(output_dir, "xml")
        md_dir = os.path.join(output_dir, "md")
        Path(pdf_dir).mkdir(parents=True, exist_ok=True)
        Path(xml_dir).mkdir(parents=True, exist_ok=True)
        Path(md_dir).mkdir(parents=True, exist_ok=True)

        # Skip if already downloaded in any format (PDF, XML, JSON)
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
                # XML/JSON: skip if file is non-empty
                if os.path.getsize(existing_path) > 0:
                    safe_print(f"SKIP: Already exists, skipping: {existing_path}")
                    return True
                safe_print(f"Existing {ext} file is empty, re-downloading: {existing_path}")
                try:
                    os.remove(existing_path)
                except Exception as e:
                    safe_print(f"ERROR: Could not remove existing file: {e}")
                    return False

        # Step 1: Resolve DOI to publisher URL
        doi_url = f"https://doi.org/{doi}"
        try:
            response = self._request("HEAD", doi_url, allow_redirects=True)
            if response.status_code >= 400:
                response = self._request("GET", doi_url, allow_redirects=True)
            paper_url = response.url
        except Exception as e:
            safe_print(f"Error resolving DOI: {e}")
            return False

        # Step 2: Detect publisher and use appropriate strategy
        publisher = self._detect_publisher(paper_url)

        # Print DOI resolution info as an atomic block
        safe_print_block(
            f"\nProcessing DOI: {doi}",
            f"  Paper URL: {paper_url}",
            f"  Detected publisher: {publisher}",
        )

        # Step 3: Get PDF URL based on publisher
        pdf_url = self._get_pdf_url_by_publisher(paper_url, publisher, doi)

        if not pdf_url:
            # Try Unpaywall before giving up on PDF
            pdf_url = self._get_unpaywall_pdf_url(doi)

        if pdf_url:
            # Step 4: Download PDF
            pdf_downloaded = False
            try:
                pdf_downloaded = self._download_pdf(pdf_url, doi, pdf_dir)
            except PermissionError:
                safe_print(f"ERROR: Permission denied (HTTP 403/401) for {doi}")

            if pdf_downloaded:
                return True

        # Fallback: try publisher-specific XML/full-text APIs
        if publisher == "elsevier":
            xml_ok = self._download_elsevier_api(doi, xml_dir, md_dir, pdf_dir)
            if xml_ok:
                return True
        # elif publisher == "wiley":
        #     xml_ok = self._download_wiley_api(doi, xml_dir, md_dir, pdf_dir)
        #     if xml_ok:
        #         return True
        # elif publisher in ("springer", "nature"):
        #     xml_ok = self._download_springer_nature_api(doi, xml_dir, md_dir, pdf_dir)
        #     if xml_ok:
        #         return True

        # Last resort: Unpaywall may have an OA PDF even when publisher strategy failed
        if pdf_url is None:
            # Already tried Unpaywall above for pdf_url discovery
            pass
        elif not pdf_downloaded:
            # Publisher PDF failed — try Unpaywall as alternative source
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
        """Detect the publisher from URL"""
        domain = urlparse(url).netloc.lower()
        
        if 'springer' in domain or 'link.springer.com' in domain:
            return 'springer'
        elif 'sciencedirect' in domain or 'elsevier' in domain:
            return 'elsevier'
        elif 'ieee' in domain:
            return 'ieee'
        elif 'wiley' in domain:
            return 'wiley'
        elif 'nature.com' in domain:
            return 'nature'
        elif 'science.org' in domain or 'sciencemag.org' in domain:
            return 'science'
        elif 'oup.com' in domain or 'oxford' in domain:
            return 'oxford'
        elif 'plos.org' in domain:
            return 'plos'
        elif 'journals.sagepub.com' in domain:
            return 'sage'
        elif 'tandfonline.com' in domain:
            return 'taylor'
        elif 'cureus.com' in domain:
            return 'cureus'
        else:
            return 'unknown'
    
    def _get_pdf_url_by_publisher(self, paper_url, publisher, doi):
        """Get PDF URL using publisher-specific strategies"""
        
        if publisher == 'springer':
            return self._get_springer_pdf(paper_url, doi)
        elif publisher == 'elsevier':
            return self._get_elsevier_pdf(paper_url)
        elif publisher == 'ieee':
            return self._get_ieee_pdf(paper_url)
        elif publisher == 'wiley':
            return self._get_wiley_pdf(paper_url)
        elif publisher == 'nature':
            return self._get_nature_pdf(paper_url)
        elif publisher == 'cureus':
            return self._get_cureus_pdf(paper_url)
        else:
            # Generic fallback
            return self._get_generic_pdf(paper_url)
    
    def _get_springer_pdf(self, paper_url, doi):
        """
        Springer/SpringerLink PDF download
        Format: https://link.springer.com/content/pdf/10.1007/...pdf
        """
        # Method 1: Direct PDF URL construction
        pdf_url = f"https://link.springer.com/content/pdf/{doi}.pdf"
        safe_print(f"  Trying Springer PDF URL: {pdf_url}")
        
        # Test if this URL works
        response = self._request("HEAD", pdf_url, allow_redirects=True)
        if response.status_code == 200:
            return pdf_url
        
        # Method 2: Parse the page for PDF link
        try:
            response = self._request("GET", paper_url)
            content = response.text
            
            # Look for PDF download link
            patterns = [
                r'href="(/content/pdf/[^"]+\.pdf)"',
                r'href="(https://link\.springer\.com/content/pdf/[^"]+\.pdf)"',
                r'data-article-pdf="([^"]+)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except:
            pass
        
        return None
    
    def _get_elsevier_pdf(self, paper_url):
        """
        Elsevier/ScienceDirect PDF download.

        Follows the linkinghub redirect to the actual article page, then
        tries multiple strategies to locate the PDF URL.
        """
        article_url = paper_url  # fallback
        content = ""

        # linkinghub.elsevier.com often uses meta-refresh / JS redirects that
        # HTTP clients cannot follow.  When we detect we're still on linkinghub,
        # construct the canonical ScienceDirect URL from the PII and fetch that
        # instead.
        pii = _extract_pii(paper_url)
        if pii and "linkinghub" in paper_url:
            article_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
            safe_print(f"  Resolved linkinghub → {article_url}")
        else:
            article_url = paper_url

        try:
            response = self._request("GET", article_url)
            article_url = response.url  # update with final URL after any HTTP redirects
            content = response.text
            safe_print(f"  Elsevier article URL: {article_url}")

            # Check if the article page looks like an error page.
            if response.status_code >= 400 or "there was a problem" in content.lower():
                safe_print(f"  Warning: article page returned error (status {response.status_code})")
                content = ""  # don't try to parse error pages

        except Exception as e:
            safe_print(f"  Elsevier page fetch failed: {e}")

        if content:
            # Method 1: citation_pdf_url meta tag (most reliable across Elsevier sites)
            meta_match = re.search(
                r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
                content, re.IGNORECASE,
            )
            if meta_match:
                pdf_url = meta_match.group(1)
                self._elsevier_referer = article_url
                safe_print(f"  Found citation_pdf_url: {pdf_url}")
                return pdf_url

            # Method 2: Look for PDF link patterns in page source
            patterns = [
                r'pdfurl":"([^"]+)"',
                r'href="([^"]*pdfft[^"]*)"',
                r'href="([^"]*/pdf/download[^"]*)"',
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace('\\/', '/')
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(article_url, pdf_url)
                    self._elsevier_referer = article_url
                    return pdf_url

        # Fallback: construct pdfft URL from PII.
        # Try the actual article URL first (it's the redirect destination), then the original.
        for candidate_url in (article_url, paper_url):
            pii_match = re.search(r'/pii/([A-Z0-9]+)', candidate_url, re.IGNORECASE)
            if pii_match:
                pii = pii_match.group(1)
                # Use the actual article domain when it's a known Elsevier site.
                parsed = urlparse(article_url)
                if 'sciencedirect.com' in parsed.netloc:
                    base = f"{parsed.scheme}://{parsed.netloc}"
                else:
                    base = "https://www.sciencedirect.com"
                self._elsevier_referer = f"{base}/science/article/pii/{pii}"
                pdfft = f"{base}/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true"
                safe_print(f"  Constructed pdfft fallback: {pdfft}")
                return pdfft

        return None
    
    def _get_ieee_pdf(self, paper_url):
        """
        IEEE PDF download
        """
        try:
            response = self._request("GET", paper_url)
            content = response.text
            
            # Extract article number
            match = re.search(r'arnumber[=/](\d+)', paper_url)
            if match:
                article_num = match.group(1)
                pdf_url = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={article_num}"
                return pdf_url
            
            # Look for PDF link in page
            patterns = [
                r'"pdfUrl":"([^"]+)"',
                r'href="([^"]*\.pdf[^"]*)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace('\\/', '/')
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except:
            pass
        
        return None
    
    def _get_wiley_pdf(self, paper_url):
        """
        Wiley PDF download
        """
        try:
            response = self._request("GET", paper_url)
            content = response.text
            
            patterns = [
                r'href="([^"]*\/pdfdirect\/[^"]*)"',
                r'citation_pdf_url" content="([^"]+)"',
                r'href="([^"]*\.pdf)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except:
            pass
        
        return None
    
    def _get_nature_pdf(self, paper_url):
        """
        Nature PDF download
        """
        # Nature PDF URLs are usually straightforward
        pdf_url = paper_url.replace('.html', '.pdf')
        if not pdf_url.endswith('.pdf'):
            pdf_url = paper_url + '.pdf'

        return pdf_url

    def _get_cureus_pdf(self, paper_url):
        """
        Cureus PDF download (open-access journal).

        Cureus article URLs look like:
            https://www.cureus.com/articles/453946-some-title-slug
        The PDF is typically available at:
            https://www.cureus.com/articles/453946.pdf
        or via the citation_pdf_url meta tag.
        """
        try:
            response = self._request("GET", paper_url)
            content = response.text

            # Method 1: citation_pdf_url meta tag
            meta_match = re.search(
                r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
                content, re.IGNORECASE,
            )
            if meta_match:
                pdf_url = meta_match.group(1)
                safe_print(f"  Found Cureus citation_pdf_url: {pdf_url}")
                return pdf_url

            # Method 2: Look for explicit PDF download links
            patterns = [
                r'href="([^"]*\.pdf[^"]*)"',
                r'href="([^"]*download[^"]*pdf[^"]*)"',
            ]
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    pdf_url = match.group(1)
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    safe_print(f"  Found Cureus PDF link: {pdf_url}")
                    return pdf_url
        except Exception as e:
            safe_print(f"  Cureus page fetch failed: {e}")

        # Method 3: Construct PDF URL from article ID
        # e.g. /articles/453946-title-slug -> /articles/453946.pdf
        match = re.search(r'/articles/(\d+)', paper_url)
        if match:
            article_id = match.group(1)
            pdf_url = f"https://www.cureus.com/articles/{article_id}.pdf"
            safe_print(f"  Constructed Cureus PDF URL: {pdf_url}")
            return pdf_url

        return None

    def _get_unpaywall_pdf_url(self, doi: str) -> str | None:
        """Query Unpaywall API for an open-access PDF URL.

        Endpoint: https://api.unpaywall.org/v2/{DOI}?email={EMAIL}
        Returns the best available OA PDF URL, or None.
        """
        email = os.getenv("UNPAYWALL_EMAIL")
        if not email:
            return None

        encoded_doi = quote(doi, safe="")
        url = f"https://api.unpaywall.org/v2/{encoded_doi}"
        params = {"email": email}

        try:
            response = self._request("GET", url, params=params)
        except Exception as e:
            safe_print(f"  Unpaywall API request failed: {e}")
            return None

        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except Exception:
            return None

        # Try best_oa_location first, then iterate all oa_locations
        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf")
        if pdf_url:
            safe_print(f"  Unpaywall: found OA PDF: {pdf_url}")
            return pdf_url

        for loc in data.get("oa_locations") or []:
            pdf_url = loc.get("url_for_pdf")
            if pdf_url:
                safe_print(f"  Unpaywall: found OA PDF (alt location): {pdf_url}")
                return pdf_url

        # No direct PDF link — try landing page URL as last resort
        landing = best.get("url_for_landing_page")
        if landing:
            safe_print(f"  Unpaywall: no direct PDF, landing page: {landing}")

        return None

    def _get_generic_pdf(self, paper_url):
        """
        Generic PDF detection for unknown publishers
        """
        try:
            response = self._request("GET", paper_url)
            content = response.text
            
            # Try multiple patterns
            patterns = [
                r'citation_pdf_url" content="([^"]+)"',
                r'href="([^"]*\.pdf)"',
                r'data-article-pdf="([^"]+)"',
                r'data-pdf-url="([^"]+)"',
                r'href="([^"]*download[^"]*\.pdf[^"]*)"',
                r'"pdfUrl":"([^"]+)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    pdf_url = match.group(1)
                    pdf_url = pdf_url.replace('\\/', '/')
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except:
            pass
        
        return None
    
    def _download_pdf(self, pdf_url, doi, output_dir):
        """Download the PDF file with validation (PDF-only; non-PDF responses are ignored)."""
        filename = doi.replace("/", "_") + ".pdf"
        filepath = os.path.join(output_dir, filename)
        part_path = filepath + ".part"
        max_attempts = 3

        # Derive a proper Referer (article page, not the PDF URL itself).
        referer = getattr(self, "_elsevier_referer", None)
        if not referer:
            # Generic: strip filename / query to approximate the article page.
            parsed = urlparse(pdf_url)
            path = parsed.path.rsplit("/", 1)[0] if "/" in parsed.path else parsed.path
            referer = f"{parsed.scheme}://{parsed.netloc}{path}"

        # Set headers for PDF download
        headers = {
            "Accept": "application/pdf, application/octet-stream, */*",
            "Referer": referer,
        }
        if not self._using_curl_cffi:
            headers.update({
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
            })

        # Reset the Elsevier referer so it doesn't leak to unrelated downloads.
        self._elsevier_referer = None

        # For ScienceDirect pdfft URLs, visit the article page once before
        # downloading to ensure session/CSRF cookies are set on the correct domain.
        if "sciencedirect.com" in pdf_url and "/pdfft" in pdf_url:
            article_page = pdf_url.split("/pdfft")[0]
            try:
                self._request("GET", article_page)
            except Exception:
                pass  # best-effort; proceed with download anyway

        for attempt in range(1, max_attempts + 1):
            try:
                # Remove stale partial file from previous attempts, if any.
                if os.path.exists(part_path):
                    try:
                        os.remove(part_path)
                    except Exception:
                        pass

                safe_print(f"  Downloading from: {pdf_url} (attempt {attempt}/{max_attempts})")

                response = self._request("GET", pdf_url, stream=True, headers=headers)
                try:
                    if response.status_code in (401, 403):
                        raise PermissionError(f"HTTP {response.status_code}")
                    if response.status_code != 200:
                        raise RuntimeError(f"HTTP {response.status_code}")

                    it = response.iter_content(chunk_size=8192)
                    first_chunk = next(it, b"")

                    if not first_chunk or not first_chunk.startswith(b"%PDF"):
                        ct = response.headers.get("Content-Type", "")
                        raise RuntimeError(f"Non-PDF response (Content-Type: {ct})")

                    with open(part_path, "wb") as f:
                        f.write(first_chunk)
                        for chunk in it:
                            if chunk:
                                f.write(chunk)
                finally:
                    response.close()

                # Validate the completed file before moving into place.
                if not self._is_pdf_file_valid(part_path):
                    raise RuntimeError("Downloaded file failed PDF validation (possibly truncated)")

                os.replace(part_path, filepath)
                safe_print(f"  OK: Successfully downloaded: {filepath}")
                return True

            except PermissionError:
                # 401/403 — don't retry, let caller handle auth.
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except Exception:
                    pass
                raise  # propagate to download_paper

            except Exception as e:
                # Ensure we don't leave behind corrupted partial files.
                try:
                    if os.path.exists(part_path):
                        os.remove(part_path)
                except Exception:
                    pass

                if attempt < max_attempts:
                    safe_print(f"  Attempt {attempt}/{max_attempts} failed: {e}")
                    # Small retry backoff (+ jitter). DomainBackoff still handles 429/5xx globally.
                    time.sleep(0.5 * attempt + random.uniform(0.0, 0.3))
                    continue

                safe_print(f"  ERROR: Download failed after {max_attempts} attempts: {e}")
                return False

    def _convert_xml_to_pdf(self, xml_path: str, md_dir: str, pdf_dir: str) -> bool:
        """Convert downloaded XML to PDF via XML → MD → PDF pipeline.

        Keeps the intermediate .md file regardless of PDF rendering success.
        Returns True if PDF was generated successfully, False otherwise.
        """
        xml_p = Path(xml_path)
        stem = xml_p.stem  # e.g. "10.1016_j.test"
        md_p = Path(md_dir) / (stem + ".md")
        pdf_p = Path(pdf_dir) / (stem + ".pdf")

        # Step 1: XML → dict
        try:
            info = parse_xml(xml_p)
        except Exception as e:
            safe_print(f"  XML parse failed: {e}")
            return False

        if not info:
            safe_print("  XML parse returned empty result")
            return False

        # Step 2: dict → Markdown string → write .md file
        try:
            md_text = build_md(info)
            md_p.write_text(md_text, encoding="utf-8")
            safe_print(f"  OK: Markdown generated: {md_p}")
        except Exception as e:
            safe_print(f"  Markdown generation failed: {e}")
            return False

        # Step 3: MD → PDF via WeasyPrint
        try:
            convert_md_to_pdf(md_p, pdf_p)
        except Exception as e:
            safe_print(f"  PDF rendering failed (MD preserved): {e}")
            return False

        if pdf_p.exists() and pdf_p.stat().st_size > 0:
            safe_print(f"  OK: PDF rendered from XML: {pdf_p}")
            return True

        safe_print("  PDF rendering produced empty file")
        return False

    def _download_elsevier_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        """Fallback: download Elsevier full text XML via Article Retrieval API."""
        api_key = os.getenv("ELSEVIER_API_KEY")
        if not api_key:
            safe_print("  Elsevier API key not configured, skipping API fallback")
            return False

        filename = doi.replace("/", "_") + ".xml"
        filepath = os.path.join(xml_dir, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            safe_print(f"  SKIP: XML already exists: {filepath}")
            return True

        encoded_doi = quote(doi, safe="")
        url = f"https://api.elsevier.com/content/article/doi/{encoded_doi}"
        headers = {
            "X-ELS-APIKey": api_key,
            "Accept": "application/xml",
        }
        params = {"view": "FULL"}

        try:
            response = self._request("GET", url, headers=headers, params=params)
        except Exception as e:
            safe_print(f"  Elsevier API request failed: {e}")
            return False

        status_code = response.status_code
        if status_code == 200:
            content = response.content
            if not content:
                safe_print("  Elsevier API returned empty XML content")
                return False
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
            safe_print(f"  Elsevier API: DOI not found (HTTP 404): {doi}")
            return False

        if status_code == 429:
            remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
            safe_print(f"  Elsevier API rate limited (HTTP 429), X-RateLimit-Remaining={remaining}")
            return False

        safe_print(f"  Elsevier API request failed (HTTP {status_code})")
        return False

    def _download_wiley_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        """Fallback: download Wiley full-text XML via TDM API.

        Requires WILEY_TDM_TOKEN in .env.
        Endpoint: https://api.wiley.com/onlinelibrary/tdm/v1/articles/{DOI}
        """
        token = os.getenv("WILEY_TDM_TOKEN")
        if not token:
            safe_print("  Wiley TDM token not configured, skipping API fallback")
            return False

        filename = doi.replace("/", "_") + ".xml"
        filepath = os.path.join(xml_dir, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            safe_print(f"  SKIP: XML already exists: {filepath}")
            return True

        encoded_doi = quote(doi, safe="")
        url = f"https://api.wiley.com/onlinelibrary/tdm/v1/articles/{encoded_doi}"
        headers = {
            "Wiley-TDM-Client-Token": token,
            "Accept": "application/xml",
        }

        try:
            response = self._request("GET", url, headers=headers)
        except Exception as e:
            safe_print(f"  Wiley TDM API request failed: {e}")
            return False

        status_code = response.status_code
        if status_code == 200:
            content = response.content
            if not content:
                safe_print("  Wiley TDM API returned empty content")
                return False
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
            safe_print(f"  Wiley TDM API auth/permission error (HTTP {status_code}) for DOI {doi}")
            return False

        if status_code == 404:
            safe_print(f"  Wiley TDM API: DOI not found (HTTP 404): {doi}")
            return False

        if status_code == 429:
            safe_print(f"  Wiley TDM API rate limited (HTTP 429)")
            return False

        safe_print(f"  Wiley TDM API request failed (HTTP {status_code})")
        return False

    def _download_springer_nature_api(self, doi: str, xml_dir: str, md_dir: str, pdf_dir: str) -> bool:
        """Fallback: download Springer/Nature full-text XML via Springer Nature API.

        Requires SPRINGER_NATURE_API_KEY in .env.
        Tries open-access JATS XML first, then metadata endpoint.
        Endpoint: https://api.springernature.com/openaccess/jats/doi/{DOI}?api_key={key}
        """
        api_key = os.getenv("SPRINGER_NATURE_API_KEY")
        if not api_key:
            safe_print("  Springer Nature API key not configured, skipping API fallback")
            return False

        filename = doi.replace("/", "_") + ".xml"
        filepath = os.path.join(xml_dir, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            safe_print(f"  SKIP: XML already exists: {filepath}")
            return True

        encoded_doi = quote(doi, safe="")

        # Try open-access JATS XML endpoint
        url = f"https://api.springernature.com/openaccess/jats/doi/{encoded_doi}"
        params = {"api_key": api_key}

        try:
            response = self._request("GET", url, params=params)
        except Exception as e:
            safe_print(f"  Springer Nature API request failed: {e}")
            return False

        status_code = response.status_code
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


# ==================== USAGE EXAMPLES ====================

def example_springer_paper():
    """
    Example: Download from Springer
    """
    downloader = ImprovedPaperDownloader()
    # Springer DOI example
    doi = "10.1007/978-981-96-6948-6_7"
    downloader.download_paper(doi)


def _read_dois_from_file(doi_file_path: Path) -> list[str]:
    dois: list[str] = []
    with open(doi_file_path, "r", encoding="utf-8") as f:
        for line in f:
            doi = line.strip()
            # Skip empty lines and comments
            if doi and not doi.startswith("#"):
                dois.append(doi)
    return dois


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def main():
    """Main interface (parallel bulk download)"""
    parser = argparse.ArgumentParser(description="Download PDFs from a DOI list.")
    parser.add_argument("--doi-file", default="resources/doi.txt", help="Path to a text file containing DOIs.")
    parser.add_argument("--output-dir", default="downloads", help="Directory to save PDFs.")
    parser.add_argument("--workers", type=int, default=4, help="Max concurrent downloads (default: 4).")
    args = parser.parse_args()

    doi_file_path = Path(args.doi_file)
    output_dir = str(args.output_dir)
    workers = max(1, int(args.workers))

    print("=" * 60)
    print("Improved Research Paper Downloader (PDF-only)")
    print(f"DOI file   : {doi_file_path}")
    print(f"Output dir : {output_dir}")
    print(f"Workers    : {workers}")
    print("=" * 60)
    print()

    if not doi_file_path.exists():
        print(f"\nERROR: Could not find the DOI file at '{doi_file_path}'.")
        print("Please create it and try again.")
        return

    try:
        dois = _read_dois_from_file(doi_file_path)
    except Exception as e:
        print(f"ERROR: Error reading file: {e}")
        return

    dois = _dedupe_preserve_order(dois)
    if not dois:
        print("No valid DOIs found in the file.")
        return

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print(f"Found {len(dois)} DOI(s). Starting download...")

    shared_backoff = DomainBackoff()

    tls = threading.local()

    def worker(doi: str) -> tuple[str, bool]:
        downloader = getattr(tls, "downloader", None)
        if downloader is None:
            downloader = ImprovedPaperDownloader(
                backoff=shared_backoff,
            )
            tls.downloader = downloader
        ok = downloader.download_paper(doi, output_dir=output_dir)
        return doi, ok

    success_count = 0
    done_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(worker, doi) for doi in dois]

        for fut in as_completed(futures):
            doi, ok = fut.result()
            done_count += 1
            success_count += int(ok)
            status = "OK" if ok else "FAIL"
            safe_print(f"[{done_count}/{len(dois)}] {status} {doi}")

    print("=" * 60)
    print(f"Summary: {success_count}/{len(dois)} papers downloaded successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
