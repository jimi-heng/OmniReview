from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .models import Paper

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


def load_pdf_bytes(pdf_path: Path, pages: Optional[List[int]] = None) -> bytes:
    """Load PDF bytes, optionally extracting specific pages (1-based)."""
    data = pdf_path.read_bytes()
    if pages is None:
        return data

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for page extraction. Install `pymupdf`.")

    with fitz.open(stream=data, filetype="pdf") as src:
        page_count = src.page_count
        selected = [p for p in pages if 1 <= p <= page_count]
        if not selected:
            return data

        out = fitz.open()
        for p in selected:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        return out.tobytes()


def parse_pages_spec(spec: str) -> Optional[List[int]]:
    """Parse page specification string into list of page numbers."""
    s = (spec or "").strip().lower()
    if s in {"all", "*"}:
        return None

    pages: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            p = int(part)
            if p > 0:
                pages.add(p)
    return sorted(pages) if pages else None


def extract_pdf_title(pdf_path: Path) -> str:
    """Extract article title from PDF metadata or first page content."""
    if fitz is None:
        return pdf_path.stem

    try:
        with fitz.open(str(pdf_path)) as doc:
            metadata = doc.metadata
            if metadata:
                meta_title = str(metadata.get("title") or "").strip()
                if len(meta_title) >= 6:
                    return meta_title

            if doc.page_count > 0:
                text = doc[0].get_text("text").strip()
                if text:
                    for line in text.split("\n"):
                        line = line.strip()
                        if len(line) >= 10:
                            return line[:300]
    except Exception:
        pass

    return pdf_path.stem


def discover_pdfs(resources_dir: Path) -> List[Paper]:
    """Find all PDF files in resources directory (recursively)."""
    pdfs = sorted(
        [p for p in resources_dir.rglob("*.pdf") if p.is_file()],
        key=lambda p: str(p).lower(),
    )
    papers: List[Paper] = []
    for i, path in enumerate(pdfs, start=1):
        resolved = path.resolve()
        papers.append(Paper(paper_id=i, path=resolved, title=extract_pdf_title(resolved)))
    return papers

