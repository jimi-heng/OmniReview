import fitz
import unicodedata
from rapidfuzz import fuzz
from pathlib import Path

COLORS = {
    "Population": (1, 0, 0),  #红
    "Intervention": (0, 0, 1), #蓝
    "Comparison": (0, 0.6, 0), #绿
    "Outcome": (1, 0.5, 0), #橙
    "Extra": (0.6, 0, 0.6) #紫
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


def highlight_pdf(
    input_pdf: Path,
    output_pdf: Path,
    evidences: dict[str, str],
    threshold: int = 90
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

        # 遍历五项证据
        for component, evidence in evidences.items():

            if not evidence.strip():
                continue

            norm_evidence = normalize(evidence)

            best_score = 0
            best_range = None

            for i in range(len(full_text) - len(norm_evidence) + 1):
                window = full_text[i:i + len(norm_evidence)]
                score = fuzz.ratio(window, norm_evidence)

                if score > best_score:
                    best_score = score
                    best_range = (i, i + len(norm_evidence))

                if best_score == 100:
                    break

            if best_score >= threshold and best_range:
                start, end = best_range

                highlight_rects = []

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

                    color = COLORS.get(component, (1, 0, 0))
                    annot.set_colors(stroke=color)
                    annot.set_opacity(0.3)
                    annot.update()

    doc.save(output_pdf)
    doc.close()