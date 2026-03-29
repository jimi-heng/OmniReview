# Author: Team 04
# This file is developed by our team

import fitz
import unicodedata
from rapidfuzz import fuzz
from pathlib import Path

COLORS = {
    "study_design": (0.7, 0.6, 0.1),  # Dark yellow (methodology)
    "population": (0.9, 0.2, 0.2),  # Red (population)
    "intervention": (0.2, 0.3, 0.9),  # Blue (intervention)
    "indicator": (0.9, 0.4, 0.1),  # Dark orange (indicator / measurement)
    "comparison": (0.4, 0.8, 0.4),  # Green (comparison)
    "reference": (0.8, 0.3, 0.8),  # Purple (reference group)
    "exposure": (0.2, 0.7, 0.7),  # Cyan (exposure)
    "outcomes": (1.0, 0.6, 0.1),  # Orange (outcomes)
    "additional_criteria": (0.5, 0.5, 0.5)  # Gray (additional criteria)
}


def rgb255_to_1(rgb):
    """
    Convert RGB values from 0–255 range to 0–1 range.

    Args:
        rgb (tuple[int, int, int]): RGB color tuple in 0–255 scale.

    Returns:
        tuple[float, float, float]: Normalized RGB values in 0–1 scale.
    """
    return tuple(c / 255 for c in rgb)


def normalize(text: str) -> str:
    """
    Normalize text for consistent matching.

    This function:
    - Applies Unicode normalization (NFKC)
    - Removes zero-width spaces
    - Replaces non-breaking spaces
    - Fixes hyphenated line breaks
    - Converts line breaks into spaces

    Args:
        text (str): Input text.

    Returns:
        str: Normalized text.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "")
    text = text.replace("\xa0", " ")
    text = text.replace("-\n", "")
    text = text.replace("\n", " ")
    return text


def _find_best_match(
    full_text: str, norm_evidence: str, threshold: int
) -> tuple[int, tuple[int, int] | None]:
    """
    Find the best fuzzy match of a substring within a larger text.

    The function performs matching in three phases:
    1. Exact substring match (fast O(N))
    2. Coarse fuzzy scan (step-based)
    3. Fine-grained local search

    Args:
        full_text (str): The full normalized text extracted from PDF.
        norm_evidence (str): The normalized evidence string to match.
        threshold (int): Minimum similarity score (0–100) to accept match.

    Returns:
        tuple:
            - score (int): Best match score
            - (start, end) (tuple[int, int] | None): Match position if found,
              otherwise None
    """
    ev_len = len(norm_evidence)
    if ev_len == 0:
        return 0, None

    # Phase 1: exact match
    idx = full_text.find(norm_evidence)
    if idx >= 0:
        return 100, (idx, idx + ev_len)

    text_len = len(full_text)
    if ev_len > text_len:
        return 0, None

    # Phase 2: coarse scan
    step = max(1, ev_len // 4)
    best_score = 0
    best_pos = 0
    search_range = text_len - ev_len + 1

    for i in range(0, search_range, step):
        window = full_text[i: i + ev_len]
        score = fuzz.ratio(window, norm_evidence)
        if score > best_score:
            best_score = score
            best_pos = i
        if best_score == 100:
            return 100, (best_pos, best_pos + ev_len)

    if best_score < threshold:
        return best_score, None

    # Phase 3: fine search
    fine_start = max(0, best_pos - step)
    fine_end = min(search_range, best_pos + step + 1)

    for i in range(fine_start, fine_end):
        window = full_text[i: i + ev_len]
        score = fuzz.ratio(window, norm_evidence)
        if score > best_score:
            best_score = score
            best_pos = i
        if best_score == 100:
            break

    if best_score >= threshold:
        return best_score, (best_pos, best_pos + ev_len)

    return best_score, None


def highlight_pdf(
    input_pdf: Path,
    output_pdf: Path,
    evidences: dict[str, str],
    threshold: int = 85
) -> None:
    """
    Highlight matched evidence text in a PDF file.

    This function:
    - Extracts character-level text and bounding boxes from each page
    - Performs fuzzy matching for each evidence string
    - Maps matched text back to bounding boxes
    - Adds highlight annotations with category-specific colors

    Args:
        input_pdf (Path): Path to the original PDF file.
        output_pdf (Path): Path where the highlighted PDF will be saved.
        evidences (dict[str, str]):
            Mapping of component names to evidence text.
            Example:
                {
                    "population": "...",
                    "intervention": "...",
                    "outcomes": "..."
                }
        threshold (int, optional):
            Minimum fuzzy matching score (0–100).
            Defaults to 85.

    Returns:
        None
    """
    doc = fitz.open(input_pdf)

    for page in doc:

        raw = page.get_text("rawdict")

        full_text = ""
        char_boxes = []

        # Build character-level mapping
        for block in raw["blocks"]:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    for char in span["chars"]:
                        c = char["c"]
                        norm_c = unicodedata.normalize("NFKC", c)
                        full_text += norm_c
                        char_boxes.append(char["bbox"])

        # Process each evidence
        for component, evidence in evidences.items():

            if not evidence.strip():
                continue

            norm_evidence = normalize(evidence)
            best_score, best_range = _find_best_match(
                full_text, norm_evidence, threshold
            )

            if best_score >= threshold and best_range:
                start, end = best_range

                line_rects = []
                for i in range(start, end):
                    r = fitz.Rect(char_boxes[i])
                    if r.is_valid and not r.is_empty:
                        line_rects.append(r)

                if line_rects:
                    line_rects.sort(key=lambda r: (round(r.y0, 1), r.x0))

                    merged = []
                    current = line_rects[0]

                    for r in line_rects[1:]:
                        if abs(r.y0 - current.y0) < 1.5:
                            current.x1 = r.x1
                        else:
                            merged.append(current)
                            current = r

                    merged.append(current)

                    annot = page.add_highlight_annot(merged)

                    color = next(
                        (v for k, v in COLORS.items() if component.startswith(k)),
                        (1, 0, 0)
                    )

                    annot.set_colors(stroke=color)
                    annot.set_opacity(0.3)
                    annot.update()

    doc.save(output_pdf)
    doc.close()