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
from urllib.parse import urljoin, urlparse
import time

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
        print("ERROR: Could not find PDF link")
        print(f"   Try visiting this URL in your browser: {paper_url}")

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
                print(f"Invalid DOI format: {doi}")
                return False

        print(f"\nProcessing DOI: {doi}")

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Skip if already downloaded (useful when rerunning large DOI lists)
        existing_path = os.path.join(output_dir, doi.replace("/", "_") + ".pdf")
        if os.path.exists(existing_path):
            if self._is_pdf_file_valid(existing_path):
                print(f"SKIP: Already exists, skipping: {existing_path}")
                return True

            print(f"Existing file looks corrupted, re-downloading: {existing_path}")
            try:
                os.remove(existing_path)
            except Exception as e:
                print(f"ERROR: Could not remove existing file: {e}")
                return False

        # Step 1: Resolve DOI to publisher URL
        doi_url = f"https://doi.org/{doi}"
        try:
            response = self._request("HEAD", doi_url, allow_redirects=True)
            if response.status_code >= 400:
                response = self._request("GET", doi_url, allow_redirects=True)
            paper_url = response.url
            print(f"Paper URL: {paper_url}")
        except Exception as e:
            print(f"Error resolving DOI: {e}")
            return False

        # Step 2: Detect publisher and use appropriate strategy
        publisher = self._detect_publisher(paper_url)
        print(f"Detected publisher: {publisher}")

        # Step 3: Get PDF URL based on publisher
        pdf_url = self._get_pdf_url_by_publisher(paper_url, publisher, doi)

        if not pdf_url:
            self._handle_no_pdf(paper_url)
            return False

        # Step 4: Download PDF
        try:
            if self._download_pdf(pdf_url, doi, output_dir):
                return True
        except PermissionError:
            print(f"ERROR: Permission denied (HTTP 403/401) for {doi}")

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
        print(f"Trying Springer PDF URL: {pdf_url}")
        
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
            print(f"  Resolved linkinghub → {article_url}")
        else:
            article_url = paper_url

        try:
            response = self._request("GET", article_url)
            article_url = response.url  # update with final URL after any HTTP redirects
            content = response.text
            print(f"  Elsevier article URL: {article_url}")

            # Check if the article page looks like an error page.
            if response.status_code >= 400 or "there was a problem" in content.lower():
                print(f"  Warning: article page returned error (status {response.status_code})")
                content = ""  # don't try to parse error pages

        except Exception as e:
            print(f"  Elsevier page fetch failed: {e}")

        if content:
            # Method 1: citation_pdf_url meta tag (most reliable across Elsevier sites)
            meta_match = re.search(
                r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
                content, re.IGNORECASE,
            )
            if meta_match:
                pdf_url = meta_match.group(1)
                self._elsevier_referer = article_url
                print(f"  Found citation_pdf_url: {pdf_url}")
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
                print(f"  Constructed pdfft fallback: {pdfft}")
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

                print(f"Downloading from: {pdf_url} (attempt {attempt}/{max_attempts})")

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
                print(f"OK: Successfully downloaded: {filepath}")
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
                    print(f"Attempt {attempt}/{max_attempts} failed: {e}")
                    # Small retry backoff (+ jitter). DomainBackoff still handles 429/5xx globally.
                    time.sleep(0.5 * attempt + random.uniform(0.0, 0.3))
                    continue

                print(f"ERROR: Download failed after {max_attempts} attempts: {e}")
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
            print(f"[{done_count}/{len(dois)}] {status} {doi}")

    print("=" * 60)
    print(f"Summary: {success_count}/{len(dois)} papers downloaded successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
