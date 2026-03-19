"""
Elsevier-like full-text XML -> structured dict.

This module intentionally performs no filesystem I/O.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {
    "dc": "http://purl.org/dc/elements/1.1/",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "ce": "http://www.elsevier.com/xml/common/dtd",
    "ja": "http://www.elsevier.com/xml/ja/dtd",
    "xocs": "http://www.elsevier.com/xml/xocs/dtd",
    "xlink": "http://www.w3.org/1999/xlink",
    "tb": "http://www.elsevier.com/xml/common/table/dtd",
    "cals": "http://www.elsevier.com/xml/common/cals/dtd",
}

_CE = NS["ce"]
_TB = NS["tb"]
_CALS = NS["cals"]
_XL = NS["xlink"]


def _tag_local(elem) -> str:
    tag = elem.tag
    return tag.split("}")[-1] if "}" in tag else tag


def _is_bib_crossref(elem) -> bool:
    local = _tag_local(elem)
    if local in ("cross-ref", "cross-refs"):
        refid = elem.get("refid", "")
        first_ref = refid.split()[0] if refid else ""
        if first_ref.startswith("bib") or first_ref.startswith("sref"):
            return True
    return False


_CITATION_REMNANT = re.compile(r"\s*[\[\(]\s*[,;\-\s]*\s*[\]\)]\s*")


def _inner_text(elem) -> str:
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


def _find_text(root, *tags) -> str:
    for tag in tags:
        ns, local = tag.split(":") if ":" in tag else ("", tag)
        uri = NS.get(ns, "")
        full = f"{{{uri}}}{local}" if uri else local
        el = root.find(f".//{full}")
        if el is not None:
            return _inner_text(el)
    return ""


def _parse_col_count(tgroup) -> int:
    try:
        return int(tgroup.get("cols", "0"))
    except Exception:
        return 0


def _parse_entry(entry) -> tuple[str, int]:
    """Parse one CALS <entry>; returns (text, colspan)."""
    text = _inner_text(entry)
    cs = 1
    # CALS uses namest/nameend for span; we approximate by counting col positions when present.
    namest = entry.get("namest")
    nameend = entry.get("nameend")
    if namest and nameend:
        try:
            cs = int(nameend.replace("col", "")) - int(namest.replace("col", "")) + 1
        except Exception:
            cs = 1
    return text, max(1, cs)


def _parse_rows(rows, col_count: int) -> list[list[tuple[str, int]]]:
    parsed: list[list[tuple[str, int]]] = []
    for row in rows:
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


def _build_float_map(root) -> dict:
    float_map: dict = {}
    ce_table = f"{{{_CE}}}table"

    for tbl in root.iter(ce_table):
        tid = tbl.get("id", "")
        if not tid or tid in float_map:
            continue
        try:
            header, body = parse_cals_table(tbl)
            if header or body:
                float_map[tid] = ("table", (header, body))
        except Exception:
            # best-effort; leave unparsed tables out
            continue

    return float_map


def _collect_section_items(section, body_parts: list, float_map: dict, depth: int = 2):
    ce_title = f"{{{_CE}}}section-title"
    ce_para = f"{{{_CE}}}para"
    ce_section = f"{{{_CE}}}section"
    ce_anchor = f"{{{_CE}}}float-anchor"

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


def _parse_abstract(root) -> list[tuple[str, str]]:
    ce_abstract = f"{{{_CE}}}abstract"
    ce_abs_sec = f"{{{_CE}}}abstract-sec"
    ce_sec_title = f"{{{_CE}}}section-title"
    ce_simple_para = f"{{{_CE}}}simple-para"

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
                paras = [_inner_text(p) for p in sec.iter(ce_simple_para) if _inner_text(p)]
                text = " ".join(paras)
                if text:
                    parts.append((title, text))
            if parts:
                return parts

        text = _inner_text(abstract_el)
        if text:
            return [("", text)]

    text = _find_text(root, "dc:description")
    if text:
        return [("", text)]
    return []


def parse_xml(xml_path: Path) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()

    authors = [_inner_text(el) for el in root.findall(f".//{{{NS['dc']}}}creator")]
    float_map = _build_float_map(root)

    body_parts: list = []
    ce_section = f"{{{_CE}}}section"
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

    abstract_parts = _parse_abstract(root)

    return {
        "title": _find_text(root, "dc:title"),
        "journal": _find_text(root, "prism:publicationName"),
        "doi": _find_text(root, "prism:doi"),
        "date": _find_text(root, "prism:coverDisplayDate"),
        "authors": ", ".join(authors),
        "abstract": abstract_parts,
        "body": body_parts,
    }
