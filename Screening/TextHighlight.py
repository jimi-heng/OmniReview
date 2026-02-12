import fitz  # PyMuPDF

doc = fitz.open("../resources/lind2003.pdf")

for page in doc:
    text_instances = page.search_for("Combined supplementation with iron")

    for inst in text_instances:
        highlight = page.add_highlight_annot(inst)

        # 设置颜色 (RGB，范围 0~1)
        highlight.set_colors(stroke=(1, 0, 0))  # 红色

        highlight.update()

doc.save("../outputs/output_highlighted.pdf")
doc.close()
