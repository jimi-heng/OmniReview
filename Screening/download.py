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
from urllib.parse import urljoin, urlparse
import time


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
    def __init__(self, *, backoff: DomainBackoff | None = None, timeout: tuple[float, float] = (5.0, 30.0)):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

        self._backoff = backoff
        self._timeout = timeout

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        domain = urlparse(url).netloc.lower()
        if self._backoff and domain:
            self._backoff.wait(domain)

        kwargs.setdefault("timeout", self._timeout)
        response = self.session.request(method, url, **kwargs)

        if self._backoff and domain:
            self._backoff.on_response(domain, response.status_code)

        return response

    def _handle_no_pdf(self, paper_url: str) -> None:
        # Keep failure handling consistent across "no PDF link" and "non-PDF downloaded".
        print("✗ Could not find PDF link")
        print(f"   Try visiting this URL in your browser: {paper_url}")
    
    def download_paper(self, doi, output_dir="downloads"):
        """
        Download an open-access paper given its DOI with improved publisher handling.

        Note: This script does NOT support institutional / library login. If the target
        PDF is paywalled or requires authentication, the download will fail.
        """
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
            print(f"✓ Already exists, skipping: {existing_path}")
            return True
        
        # Step 1: Resolve DOI to publisher URL
        doi_url = f"https://doi.org/{doi}"
        try:
            # HEAD is usually enough to resolve redirects, saving time/bandwidth.
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
        if self._download_pdf(pdf_url, doi, output_dir):
            return True

        # If we downloaded non-PDF content (HTML, login page, etc.) treat it the same as "no PDF link".
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
        Elsevier/ScienceDirect PDF download
        """
        try:
            response = self._request("GET", paper_url)
            content = response.text
            
            # Look for PDF link (usually has 'pdfft' or 'pdf/download')
            patterns = [
                r'pdfurl":"([^"]+)"',
                r'href="([^"]*pdfft[^"]*)"',
                r'href="([^"]*/pdf/download[^"]*)"',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    pdf_url = match.group(1)
                    # Unescape unicode
                    pdf_url = pdf_url.replace('\\/', '/')
                    if not pdf_url.startswith('http'):
                        pdf_url = urljoin(paper_url, pdf_url)
                    return pdf_url
        except:
            pass
        
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
        try:
            print(f"Downloading from: {pdf_url}")
            
            # Set headers for PDF download
            headers = {
                'Accept': 'application/pdf,*/*',
                'Referer': pdf_url,
            }

            # Use a context manager so the connection is always released, even if we bail early
            # after checking the first bytes. (Requests streaming best practice.)
            with self._request("GET", pdf_url, stream=True, headers=headers) as response:
                if response.status_code != 200:
                    return False

                # Read first chunk to check content
                first_chunk = next(response.iter_content(chunk_size=1024), b"")
                if not first_chunk or not first_chunk.startswith(b"%PDF"):
                    # Non-PDF content (HTML login pages, error pages, etc.) -> treat as failure.
                    return False

                filename = doi.replace("/", "_") + ".pdf"
                filepath = os.path.join(output_dir, filename)

                with open(filepath, "wb") as f:
                    f.write(first_chunk)
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)

                print(f"✓ Successfully downloaded: {filepath}")
                return True
                
        except Exception as e:
            print(f"✗ Download error: {e}")
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
    parser = argparse.ArgumentParser(description="Download open-access PDFs from a DOI list.")
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
        print(f"\n✗ Error: Could not find the DOI file at '{doi_file_path}'.")
        print("Please create it and try again.")
        return

    try:
        dois = _read_dois_from_file(doi_file_path)
    except Exception as e:
        print(f"✗ Error reading file: {e}")
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
            downloader = ImprovedPaperDownloader(backoff=shared_backoff)
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
