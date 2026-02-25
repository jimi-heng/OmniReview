import fitz
import unicodedata
from rapidfuzz import fuzz

def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u200b", "")
    text = text.replace("\xa0", " ")
    text = text.replace("-\n", "")
    text = text.replace("\n", " ")
    return text

doc = fitz.open("../resources/rayyan-356507246.pdf")

evidence = " The study population comprised preschool children aged 4 years (n = 131) from one randomly chosen public school (four classes)."
norm_evidence = normalize(evidence)

for page in doc:

    raw = page.get_text("rawdict")

    full_text = ""
    char_boxes = []

    # 构建字符级文本 + bbox 映射
    for block in raw["blocks"]:
        if "lines" not in block:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                for char in span["chars"]:
                    c = char["c"]
                    norm_c = normalize(c)

                    full_text += norm_c
                    char_boxes.append(char["bbox"])

    # 模糊匹配
    best_score = 0
    best_range = None

    for i in range(len(full_text) - len(norm_evidence)):
        window = full_text[i:i+len(norm_evidence)]
        score = fuzz.ratio(window, norm_evidence)
        if score > best_score:
            best_score = score
            best_range = (i, i+len(norm_evidence))

    if best_score > 90 and best_range:
        start, end = best_range

        highlight_rects = []
        for i in range(start, end):
            highlight_rects.append(fitz.Rect(char_boxes[i]))

        highlight = page.add_highlight_annot(highlight_rects)
        highlight.set_colors(stroke=(1, 0, 0))
        highlight.update()

doc.save("../outputs/output_highlighted.pdf")
doc.close()