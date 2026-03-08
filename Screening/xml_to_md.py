"""
将 downloads/ 目录下的 Elsevier XML 文件转换为 Markdown，输出到 outputs/ 目录。
不包含图片，保留文本、表格和参考文献。
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
INPUT_DIR = BASE_DIR / "downloads"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Elsevier XML 命名空间 ───────────────────────────────────────────────────────
NS = {
    "dc":    "http://purl.org/dc/elements/1.1/",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "ce":    "http://www.elsevier.com/xml/common/dtd",
    "ja":    "http://www.elsevier.com/xml/ja/dtd",
    "xocs":  "http://www.elsevier.com/xml/xocs/dtd",
    "xlink": "http://www.w3.org/1999/xlink",
    "tb":    "http://www.elsevier.com/xml/common/table/dtd",
    "cals":  "http://www.elsevier.com/xml/common/cals/dtd",
}

_CE   = NS["ce"]
_TB   = NS["tb"]
_CALS = NS["cals"]
_XL   = NS["xlink"]


# ── 工具函数 ───────────────────────────────────────────────────────────────────

def _is_bib_crossref(elem) -> bool:
    """判断元素是否为引用文献的 cross-ref/cross-refs（refid 以 bib/sref 开头）。"""
    local = _tag_local(elem)
    if local in ("cross-ref", "cross-refs"):
        refid = elem.get("refid", "")
        # cross-refs 可能有多个 refid 用空格分隔，检查第一个
        first_ref = refid.split()[0] if refid else ""
        if first_ref.startswith("bib") or first_ref.startswith("sref"):
            return True
    return False


# 清理移除引用后残留的空括号，如 [ ] [, ] ( ) (, ) 等
_CITATION_REMNANT = re.compile(r'\s*[\[\(]\s*[,;–\-\s]*\s*[\]\)]\s*')


def _inner_text(elem) -> str:
    """递归提取元素内所有文本，跳过文献引用 cross-ref。"""
    parts = []
    if elem.text:
        parts.append(elem.text.strip())
    for child in elem:
        if _is_bib_crossref(child):
            if child.tail:
                parts.append(child.tail.strip())
            continue
        parts.append(_inner_text(child))
        if child.tail:
            parts.append(child.tail.strip())
    text = " ".join(p for p in parts if p)
    return _CITATION_REMNANT.sub(" ", text).strip()


# 需要保留为 HTML 标签的元素名（不含命名空间）
_INLINE_TAGS = {"sup", "sub", "italic", "bold"}


def _inner_html(elem) -> str:
    """递归提取文本，保留 <sup>/<sub>/<italic>/<bold> 为 HTML 标签，跳过文献引用。"""
    local = _tag_local(elem)

    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if _is_bib_crossref(child):
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_inner_html(child))
        if child.tail:
            parts.append(child.tail)
    content = _CITATION_REMNANT.sub(" ", "".join(parts)).strip()

    tag_map = {"sup": "sup", "sub": "sub", "italic": "em", "bold": "strong"}
    if local in tag_map:
        html_tag = tag_map[local]
        return f"<{html_tag}>{content}</{html_tag}>"
    return content


def _find_text(root, *tags) -> str:
    for tag in tags:
        ns, local = tag.split(":") if ":" in tag else ("", tag)
        uri = NS.get(ns, "")
        full = f"{{{uri}}}{local}" if uri else local
        el = root.find(f".//{full}")
        if el is not None:
            return _inner_text(el)
    return ""


def _tag_local(elem) -> str:
    tag = elem.tag
    return tag.split("}")[-1] if "}" in tag else tag


# ── CALS 表格解析 ──────────────────────────────────────────────────────────────

def _parse_col_count(tgroup) -> int:
    try:
        return int(tgroup.get("cols", 1))
    except ValueError:
        return 1


def _parse_entry(entry) -> tuple[str, int]:
    text = _inner_html(entry)
    namest = entry.get("namest", "")
    nameend = entry.get("nameend", "")
    colspan = 1
    if namest and nameend:
        try:
            s = int("".join(filter(str.isdigit, namest)))
            e = int("".join(filter(str.isdigit, nameend)))
            colspan = max(1, e - s + 1)
        except Exception:
            colspan = 1
    return (text, colspan)


def _parse_rows(row_elems, col_count: int) -> list[list[tuple[str, int]]]:
    parsed = []
    for row in row_elems:
        cells: list[tuple[str, int]] = []
        col_pos = 0
        for entry in row:
            if _tag_local(entry) != "entry":
                continue
            text, cs = _parse_entry(entry)
            cells.append((text, cs))
            col_pos += cs
            for _ in range(cs - 1):
                cells.append(("", 0))
        while col_pos < col_count:
            cells.append(("", 1))
            col_pos += 1
        parsed.append(cells)
    return parsed


def parse_cals_table(table_elem) -> tuple[list, list]:
    tgroup = None
    for child in table_elem:
        if _tag_local(child) == "tgroup":
            tgroup = child
            break
    if tgroup is None:
        return [], []

    col_count = _parse_col_count(tgroup)
    thead_rows, tbody_rows = [], []
    for child in tgroup:
        local = _tag_local(child)
        if local == "thead":
            for row in child:
                if _tag_local(row) == "row":
                    thead_rows.append(row)
        elif local == "tbody":
            for row in child:
                if _tag_local(row) == "row":
                    tbody_rows.append(row)

    header = _parse_rows(thead_rows, col_count)
    body = _parse_rows(tbody_rows, col_count)
    return header, body


# ── 浮动体映射 ─────────────────────────────────────────────────────────────────

def _build_float_map(root) -> dict:
    float_map: dict = {}
    ce_table = f"{{{_CE}}}table"

    # 只收集表格，跳过图片
    for tbl in root.iter(ce_table):
        tid = tbl.get("id", "")
        if not tid or tid in float_map:
            continue
        try:
            header, body = parse_cals_table(tbl)
            if header or body:
                float_map[tid] = ("table", (header, body))
        except Exception as e:
            print(f"    [表格解析] {tid}: {e}")

    return float_map


# ── 正文收集 ───────────────────────────────────────────────────────────────────

def _collect_section_items(section, body_parts: list, float_map: dict, depth: int = 2):
    """递归收集 section 内容，depth 控制 heading 级别。"""
    ce_title   = f"{{{_CE}}}section-title"
    ce_para    = f"{{{_CE}}}para"
    ce_section = f"{{{_CE}}}section"
    ce_anchor  = f"{{{_CE}}}float-anchor"

    title_el = section.find(ce_title)
    if title_el is not None:
        t = _inner_text(title_el)
        if t:
            body_parts.append(("heading", t, depth))

    for child in section:
        tag = child.tag

        if tag == ce_para:
            t = _inner_text(child)
            if t:
                body_parts.append(("para", t))
            for anchor in child.iter(ce_anchor):
                refid = anchor.get("refid", "")
                if refid and refid in float_map:
                    body_parts.append(float_map[refid])

        elif tag == ce_section:
            _collect_section_items(child, body_parts, float_map, depth=min(depth + 1, 6))

        elif tag == ce_anchor:
            refid = child.get("refid", "")
            if refid and refid in float_map:
                body_parts.append(float_map[refid])


# ── 结构化摘要解析 ─────────────────────────────────────────────────────────────

def _parse_abstract(root) -> list[tuple[str, str]]:
    """解析 ce:abstract，返回 [(title, text), ...] 列表。
    非结构化摘要返回 [("", text)]，无摘要返回空列表。"""
    ce_abstract = f"{{{_CE}}}abstract"
    ce_abs_sec = f"{{{_CE}}}abstract-sec"
    ce_sec_title = f"{{{_CE}}}section-title"
    ce_simple_para = f"{{{_CE}}}simple-para"

    # 优先找 class="author" 的摘要
    abstract_el = None
    for ab in root.iter(ce_abstract):
        if ab.get("class") == "author":
            abstract_el = ab
            break
    if abstract_el is None:
        for ab in root.iter(ce_abstract):
            abstract_el = ab
            break

    if abstract_el is not None:
        sections = list(abstract_el.iter(ce_abs_sec))
        if sections:
            parts = []
            for sec in sections:
                title_el = sec.find(ce_sec_title)
                title = _inner_text(title_el) if title_el is not None else ""
                # 收集该 section 内所有 simple-para
                paras = [_inner_text(p) for p in sec.iter(ce_simple_para) if _inner_text(p)]
                text = " ".join(paras)
                if text:
                    parts.append((title, text))
            if parts:
                return parts
        # 非结构化：直接取全文
        text = _inner_text(abstract_el)
        if text:
            return [("", text)]

    # fallback: dc:description
    text = _find_text(root, "dc:description")
    if text:
        return [("", text)]
    return []


# ── XML 解析主函数 ─────────────────────────────────────────────────────────────

def parse_xml(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    authors = [
        _inner_text(el)
        for el in root.findall(f".//{{{NS['dc']}}}creator")
    ]

    float_map = _build_float_map(root)

    body_parts: list = []
    ce_section  = f"{{{_CE}}}section"
    ce_sections = f"{{{_CE}}}sections"

    body_el = None
    for tag_candidate in [f"{{{NS['ja']}}}body", "body", f"{{{_CE}}}body"]:
        body_el = root.find(f".//{tag_candidate}")
        if body_el is not None:
            break

    if body_el is not None:
        sections_container = body_el.find(ce_sections)
        container = sections_container if sections_container is not None else body_el
        for child in container:
            if child.tag == ce_section:
                _collect_section_items(child, body_parts, float_map)
    else:
        for section in root.iter(ce_section):
            _collect_section_items(section, body_parts, float_map)

    # 解析结构化摘要（ce:abstract -> ce:abstract-sec）
    abstract_parts = _parse_abstract(root)

    return {
        "title":      _find_text(root, "dc:title"),
        "journal":    _find_text(root, "prism:publicationName"),
        "doi":        _find_text(root, "prism:doi"),
        "date":       _find_text(root, "prism:coverDisplayDate"),
        "authors":    ", ".join(authors),
        "abstract":   abstract_parts,
        "body":       body_parts,
    }


# ── HTML 表格渲染 ──────────────────────────────────────────────────────────────

def _table_to_html(header_rows, body_rows) -> str:
    """将表格数据转换为 HTML 表格字符串，支持 colspan。"""
    all_rows = header_rows + body_rows
    if not all_rows:
        return ""

    def _render_row(row, tag: str) -> str:
        cells = []
        for text, cs in row:
            if cs == 0:
                continue
            attr = f' colspan="{cs}"' if cs > 1 else ""
            cells.append(f"      <{tag}{attr}>{text.strip()}</{tag}>")
        return "    <tr>\n" + "\n".join(cells) + "\n    </tr>"

    lines = ["<table>"]

    if header_rows:
        lines.append("  <thead>")
        for row in header_rows:
            lines.append(_render_row(row, "th"))
        lines.append("  </thead>")

    lines.append("  <tbody>")
    for row in body_rows:
        lines.append(_render_row(row, "td"))
    lines.append("  </tbody>")

    lines.append("</table>")
    return "\n".join(lines)


# ── Markdown 构建 ─────────────────────────────────────────────────────────────

def build_md(info: dict) -> str:
    parts = []

    # 标题
    title = info["title"] or "Untitled"
    parts.append(f"# {title}")
    parts.append("")

    # 元信息
    if info["authors"]:
        parts.append(f"**Authors:** {info['authors']}")
        parts.append("")
    meta_items = [info["journal"], info["doi"], info["date"]]
    meta = " | ".join(filter(None, meta_items))
    if meta:
        parts.append(f"*{meta}*")
        parts.append("")

    # 摘要
    if info["abstract"]:
        parts.append("## Abstract")
        parts.append("")
        for title, text in info["abstract"]:
            if title:
                parts.append(f"**{title}**")
                parts.append("")
            parts.append(text)
            parts.append("")

    # 正文
    for item in info["body"]:
        kind = item[0]

        if kind == "heading":
            level = item[2] if len(item) > 2 else 2
            parts.append(f"{'#' * level} {item[1]}")
            parts.append("")

        elif kind == "para":
            parts.append(item[1])
            parts.append("")

        elif kind == "table":
            header_rows, body_rows = item[1]
            table_md = _table_to_html(header_rows, body_rows)
            if table_md:
                parts.append(table_md)
                parts.append("")

        # 跳过 image 类型

    return "\n".join(parts)


# ── 入口 ───────────────────────────────────────────────────────────────────────

def main():
    xml_files = list(INPUT_DIR.glob("*.xml"))
    if not xml_files:
        print("downloads/ 中没有找到 XML 文件")
        return

    print(f"找到 {len(xml_files)} 个 XML 文件，开始转换...")
    ok, fail = 0, 0
    for xml_file in xml_files:
        out_path = OUTPUT_DIR / (xml_file.stem + ".md")
        try:
            info = parse_xml(xml_file)
            md_text = build_md(info)
            out_path.write_text(md_text, encoding="utf-8")
            print(f"  [OK] {xml_file.name} -> {out_path.name}")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {xml_file.name}: {e}")
            fail += 1

    print(f"\n完成：{ok} 成功，{fail} 失败")


if __name__ == "__main__":
    main()
