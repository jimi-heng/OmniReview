# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .downloader import DomainBackoff, ImprovedPaperDownloader, safe_print

SCREENING_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SCREENING_DIR.parent


def example_springer_paper() -> None:
    downloader = ImprovedPaperDownloader()
    doi = "10.1007/978-981-96-6948-6_7"
    downloader.download_paper(doi)


def _read_dois_from_file(doi_file_path: Path) -> list[str]:
    dois: list[str] = []
    with open(doi_file_path, "r", encoding="utf-8") as f:
        for line in f:
            doi = line.strip()
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


def main(argv: list[str] | None = None) -> int:
    """Parallel bulk download. Returns a process exit code."""
    parser = argparse.ArgumentParser(description="Download PDFs from a DOI list.")
    parser.add_argument("--doi-file", default="resources/doi.txt", help="Path to a text file containing DOIs.")
    parser.add_argument("--output-dir", default="downloads", help="Directory to save PDFs.")
    parser.add_argument("--workers", type=int, default=4, help="Max concurrent downloads (default: 4).")
    args = parser.parse_args(argv)

    doi_file_path = (REPO_ROOT / args.doi_file).resolve()
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
        return 2

    try:
        dois = _read_dois_from_file(doi_file_path)
    except Exception as e:
        print(f"ERROR: Error reading file: {e}")
        return 2

    dois = _dedupe_preserve_order(dois)
    if not dois:
        print("No valid DOIs found in the file.")
        return 0

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
            safe_print(f"[{done_count}/{len(dois)}] {status} {doi}")

    print("=" * 60)
    print(f"Summary: {success_count}/{len(dois)} papers downloaded successfully")
    print("=" * 60)
    return 0

