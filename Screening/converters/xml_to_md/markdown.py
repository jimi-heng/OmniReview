# Author: Team 04
# This file is developed by our team

from __future__ import annotations


def _table_to_html(header_rows, body_rows) -> str:
    """Convert parsed CALS table data to an HTML table string (supports colspan)."""
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


def build_md(info: dict) -> str:
    parts: list[str] = []

    title = info.get("title") or "Untitled"
    parts.append(f"# {title}")
    parts.append("")

    authors = info.get("authors") or ""
    if authors:
        parts.append(f"**Authors:** {authors}")
        parts.append("")

    meta_items = [info.get("journal"), info.get("doi"), info.get("date")]
    meta = " | ".join(filter(None, meta_items))
    if meta:
        parts.append(f"*{meta}*")
        parts.append("")

    abstract = info.get("abstract") or []
    if abstract:
        parts.append("## Abstract")
        parts.append("")
        for abs_title, text in abstract:
            if abs_title:
                parts.append(f"**{abs_title}**")
                parts.append("")
            parts.append(text)
            parts.append("")

    for item in info.get("body") or []:
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

    return "\n".join(parts)

