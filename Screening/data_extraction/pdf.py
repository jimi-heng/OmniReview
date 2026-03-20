from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional

from .models import Paper

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


DEFAULT_TARGETED_MAX_PAGES = 8
DEFAULT_NEIGHBOR_RADIUS = 1


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


def select_targeted_pages(
    pdf_path: Path,
    pages: Optional[List[int]] = None,
    *,
    keywords: Optional[List[str]] = None,
    anchor_terms: Optional[List[str]] = None,
    max_pages: int = DEFAULT_TARGETED_MAX_PAGES,
    neighbor_radius: int = DEFAULT_NEIGHBOR_RADIUS,
) -> Optional[List[int]]:
    """Select a focused subset of pages using simple keyword and section heuristics."""
    if fitz is None:
        return pages

    try:
        with fitz.open(str(pdf_path)) as doc:
            page_count = doc.page_count
            available_pages = [p for p in (pages or list(range(1, page_count + 1))) if 1 <= p <= page_count]
            if not available_pages:
                return pages

            normalized_keywords = _normalize_keywords(keywords)
            normalized_anchors = _normalize_keywords(anchor_terms)
            if not normalized_keywords and not normalized_anchors:
                return available_pages[:max_pages] if len(available_pages) > max_pages else available_pages

            scored_pages: List[tuple[int, int]] = []
            for page_number in available_pages:
                text = doc[page_number - 1].get_text("text", sort=True)
                normalized_text = _normalize_page_text(text)
                score = _score_page_text(
                    normalized_text,
                    keywords=normalized_keywords,
                    anchor_terms=normalized_anchors,
                )
                if score > 0:
                    scored_pages.append((page_number, score))

            if not scored_pages:
                return available_pages[:max_pages] if len(available_pages) > max_pages else available_pages

            selected: set[int] = set()
            available_set = set(available_pages)
            for page_number, _score in sorted(scored_pages, key=lambda item: (-item[1], item[0])):
                if len(selected) >= max_pages:
                    break
                for neighbor in range(page_number - neighbor_radius, page_number + neighbor_radius + 1):
                    if neighbor not in available_set or neighbor in selected:
                        continue
                    selected.add(neighbor)
                    if len(selected) >= max_pages:
                        break

            if not selected:
                return available_pages[:max_pages] if len(available_pages) > max_pages else available_pages
            return sorted(selected)
    except Exception:
        return pages


def build_targeted_pdf_bytes(
    pdf_path: Path,
    pages: Optional[List[int]] = None,
    *,
    keywords: Optional[List[str]] = None,
    anchor_terms: Optional[List[str]] = None,
    max_pages: int = DEFAULT_TARGETED_MAX_PAGES,
    neighbor_radius: int = DEFAULT_NEIGHBOR_RADIUS,
) -> bytes:
    """Build a focused PDF slice for phase2 prompts, falling back to the requested pages/full PDF."""
    selected_pages = select_targeted_pages(
        pdf_path,
        pages,
        keywords=keywords,
        anchor_terms=anchor_terms,
        max_pages=max_pages,
        neighbor_radius=neighbor_radius,
    )
    return load_pdf_bytes(pdf_path, selected_pages)


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


def _normalize_keywords(values: Optional[List[str]]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        text = _normalize_page_text(value)
        if len(text) < 2:
            continue
        if text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_page_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    return collapsed


def _score_page_text(text: str, *, keywords: List[str], anchor_terms: List[str]) -> int:
    if not text:
        return 0

    score = 0
    for keyword in keywords:
        if keyword and keyword in text:
            score += 6 + min(text.count(keyword), 3)

    for anchor in anchor_terms:
        if anchor and anchor in text:
            score += 3

    section_bonuses = {
        "methods": 2,
        "results": 4,
        "result": 4,
        "table": 3,
        "figure": 2,
        "baseline": 3,
        "characteristics": 2,
        "outcome": 2,
        "follow-up": 2,
        "endpoint": 2,
        "change from baseline": 2,
    }
    for marker, bonus in section_bonuses.items():
        if marker in text:
            score += bonus
    return score
