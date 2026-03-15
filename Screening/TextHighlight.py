import fitz
import unicodedata
from rapidfuzz import fuzz
from pathlib import Path

COLORS = {
    "Study Design": (0.6, 0.6, 0),   # 黄褐（方法学）
    "Population": (0.9, 0.2, 0.2),   # 红（人群）
    "Intervention": (0.2, 0.3, 0.9), # 蓝（干预）
    "Comparator": (0.1, 0.7, 0.3),   # 深绿（对照对象）
    "Comparison": (0.4, 0.8, 0.4),   # 浅绿（比较关系）
    "Outcome": (1, 0.55, 0.1),       # 橙（结果）
    "Exposure": (0.2, 0.7, 0.7),     # 青（暴露）
    "Response": (0.8, 0.3, 0.8),     # 紫粉（反应）
    "Extra": (0.5, 0.5, 0.5)         # 灰（其他）
}

def rgb255_to_1(rgb):
    return tuple(c / 255 for c in rgb)

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "")
    text = text.replace("\xa0", " ")
    text = text.replace("-\n", "")
    text = text.replace("\n", " ")
    return text


def _find_best_match(
    full_text: str, norm_evidence: str, threshold: int
) -> tuple[int, tuple[int, int] | None]:
    """Find best fuzzy match position using fast methods first, fuzzy as fallback.

    Returns (score, (start, end)) or (score, None) if no match above threshold.
    """
    ev_len = len(norm_evidence)
    if ev_len == 0:
        return 0, None

    # Phase 1: exact substring match — O(N), instant
    idx = full_text.find(norm_evidence)
    if idx >= 0:
        return 100, (idx, idx + ev_len)

    text_len = len(full_text)
    if ev_len > text_len:
        return 0, None

    # Phase 2: coarse scan — check every step positions to find approximate location
    step = max(1, ev_len // 4)
    best_score = 0
    best_pos = 0
    search_range = text_len - ev_len + 1

    for i in range(0, search_range, step):
        window = full_text[i : i + ev_len]
        score = fuzz.ratio(window, norm_evidence)
        if score > best_score:
            best_score = score
            best_pos = i
        if best_score == 100:
            return 100, (best_pos, best_pos + ev_len)

    if best_score < threshold:
        return best_score, None

    # Phase 3: fine-grained search around best coarse position
    fine_start = max(0, best_pos - step)
    fine_end = min(search_range, best_pos + step + 1)
    for i in range(fine_start, fine_end):
        window = full_text[i : i + ev_len]
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
    input_pdf: 原始PDF路径
    output_pdf: 输出高亮PDF路径
    evidences: {
        "Population": "...",
        "Intervention": "...",
        ...
    }
    """

    doc = fitz.open(input_pdf)

    for page in doc:

        raw = page.get_text("rawdict")

        full_text = ""
        char_boxes = []

        # 构建字符级映射
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

        # 遍历证据
        for component, evidence in evidences.items():

            if not evidence.strip():
                continue

            norm_evidence = normalize(evidence)

            best_score, best_range = _find_best_match(full_text, norm_evidence, threshold)

            if best_score >= threshold and best_range:
                start, end = best_range

                # 先收集字符 rect
                line_rects = []

                for i in range(start, end):
                    r = fitz.Rect(char_boxes[i])
                    if r.is_valid and not r.is_empty:
                        line_rects.append(r)

                if line_rects:

                    # 按 y 坐标排序
                    line_rects.sort(key=lambda r: (round(r.y0, 1), r.x0))

                    merged = []
                    current = line_rects[0]

                    for r in line_rects[1:]:

                        # 判断是否在同一行
                        if abs(r.y0 - current.y0) < 1.5:
                            # 只横向扩展，不改变高度
                            current.x1 = r.x1
                        else:
                            merged.append(current)
                            current = r

                    merged.append(current)

                    annot = page.add_highlight_annot(merged)

                    color = next((v for k, v in COLORS.items() if component.startswith(k)), (1, 0, 0))
                    annot.set_colors(stroke=color)
                    annot.set_opacity(0.3)
                    annot.update()

    doc.save(output_pdf)
    doc.close()
