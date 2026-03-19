from pathlib import Path
from typing import Optional

from .models import FullTextPaper

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None


def parse_pages_spec(spec: str) -> Optional[list[int]]:
    normalized = (spec or "").strip().lower()
    if normalized in {"", "all", "*"}:
        return None

    pages: set[int] = set()
    for part in normalized.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            page = int(part)
            if page > 0:
                pages.add(page)

    return sorted(pages) if pages else None


def load_pdf_bytes(pdf_path: Path, pages: Optional[list[int]]) -> bytes:
    data = pdf_path.read_bytes()
    if pages is None:
        return data

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for pdf_pages/page slicing. Install `pymupdf`.")

    with fitz.open(stream=data, filetype="pdf") as src:
        page_count = src.page_count
        selected = [page for page in pages if 1 <= page <= page_count]
        if not selected:
            return data

        with fitz.open() as out:
            for page in selected:
                out.insert_pdf(src, from_page=page - 1, to_page=page - 1)
            return out.write()


def discover_pdfs(resources_dir: Path) -> list[FullTextPaper]:
    pdfs = sorted(
        [path for path in resources_dir.rglob("*.pdf") if path.is_file()],
        key=lambda path: str(path).lower(),
    )
    papers: list[FullTextPaper] = []
    for index, path in enumerate(pdfs, start=1):
        resolved = path.resolve()
        papers.append(
            FullTextPaper(
                paper_id=index,
                title=resolved.stem,
                pdf_path=resolved,
            )
        )
    return papers
