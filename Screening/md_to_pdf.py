"""
Convert Markdown files to PDF using markdown + WeasyPrint.

Supports: headings, paragraphs, bold, italic, inline code, fenced code blocks,
          unordered/ordered lists, horizontal rules, Markdown tables, HTML tables
          (including rowspan/colspan).

System dependencies:
    WeasyPrint relies on Pango/Cairo C libraries. Install them BEFORE running:
      - macOS:        brew install pango
      - Ubuntu/Debian: sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
      - Windows:      Install GTK3 Runtime or use MSYS2. See https://doc.courtbouillon.org/weasyprint/stable/first_steps.html

Python dependencies:
    uv add markdown weasyprint

Usage:
    uv run md_to_pdf.py <input.md> [output.pdf]
    uv run md_to_pdf.py --dir <directory>          # batch convert all .md files
"""

import argparse
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

# ── CSS ──────────────────────────────────────────────────────────────────────────

CSS = """\
@page {
    size: A4;
    margin: 20mm 18mm;
}

body {
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #222;
}

/* ── Headings ─────────────────────────────────────────────────────────── */
h1 { font-size: 20pt; margin-top: 0.8em; margin-bottom: 0.4em; }
h2 { font-size: 16pt; margin-top: 0.7em; margin-bottom: 0.35em; border-bottom: 1px solid #ccc; padding-bottom: 0.15em; }
h3 { font-size: 13pt; margin-top: 0.6em; margin-bottom: 0.3em; }
h4 { font-size: 11.5pt; margin-top: 0.5em; margin-bottom: 0.25em; }
h5, h6 { font-size: 11pt; margin-top: 0.4em; margin-bottom: 0.2em; }

/* ── Paragraphs & lists ───────────────────────────────────────────────── */
p { margin: 0.4em 0; }
ul, ol { margin: 0.3em 0; padding-left: 1.8em; }
li { margin-bottom: 0.15em; }

/* ── Tables ───────────────────────────────────────────────────────────── */
table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.8em 0;
    font-size: 9.5pt;
    page-break-inside: auto;
}
thead th {
    background-color: #34495e;
    color: #fff;
    font-weight: bold;
    text-align: left;
    padding: 6px 8px;
    border: 1px solid #2c3e50;
}
tbody td {
    padding: 5px 8px;
    border: 1px solid #ddd;
    vertical-align: top;
}
tbody tr:nth-child(even) {
    background-color: #f7f8fa;
}
tbody tr:hover {
    background-color: #eef1f5;
}

/* ── Code blocks ──────────────────────────────────────────────────────── */
pre {
    background-color: #f4f4f4;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px 12px;
    font-size: 9pt;
    line-height: 1.45;
    overflow-x: auto;
    white-space: pre-wrap;
    word-wrap: break-word;
    margin: 0.6em 0;
}
pre code {
    background: none;
    border: none;
    padding: 0;
    border-radius: 0;
    font-size: inherit;
}

/* ── Inline code ──────────────────────────────────────────────────────── */
code {
    background-color: #eef0f3;
    border: 1px solid #ddd;
    border-radius: 3px;
    padding: 1px 4px;
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    font-size: 0.9em;
}

/* ── Horizontal rules ─────────────────────────────────────────────────── */
hr {
    border: none;
    border-top: 1px solid #ccc;
    margin: 1em 0;
}

/* ── Block quotes ─────────────────────────────────────────────────────── */
blockquote {
    border-left: 4px solid #ccc;
    margin: 0.6em 0;
    padding: 0.3em 1em;
    color: #555;
    background: #fafafa;
}

/* ── Images ────────────────────────────────────────────────────────────── */
img {
    max-width: 100%;
    height: auto;
}
"""

# ── Markdown extensions ──────────────────────────────────────────────────────────

MD_EXTENSIONS = [
    "tables",
    "fenced_code",
    "codehilite",
    "toc",
    "nl2br",
    "sane_lists",
]

MD_EXTENSION_CONFIGS = {
    "codehilite": {
        "css_class": "highlight",
        "guess_lang": False,
        "noclasses": True,  # inline styles so no extra CSS file needed
    },
}


# ── Conversion ───────────────────────────────────────────────────────────────────

def md_to_pdf(md_path: Path, pdf_path: Path):
    """Read a Markdown file and produce a styled PDF."""
    md_text = md_path.read_text(encoding="utf-8")

    body_html = markdown.markdown(
        md_text,
        extensions=MD_EXTENSIONS,
        extension_configs=MD_EXTENSION_CONFIGS,
    )

    full_html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
{CSS}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    HTML(string=full_html).write_pdf(str(pdf_path))
    print(f"  [OK] {md_path.name} -> {pdf_path.name}")


# ── CLI ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Markdown to PDF converter")
    parser.add_argument("input", nargs="?", help="Input .md file path")
    parser.add_argument("output", nargs="?", help="Output .pdf file path (optional)")
    parser.add_argument("--dir", help="Batch convert all .md files in the directory")
    args = parser.parse_args()

    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"Directory not found: {args.dir}")
            sys.exit(1)
        md_files = sorted(dir_path.glob("*.md"))
        if not md_files:
            print(f"No .md files found in {dir_path}")
            return
        print(f"Found {len(md_files)} Markdown file(s), converting...")
        ok, fail = 0, 0
        for md_file in md_files:
            out = md_file.with_suffix(".pdf")
            try:
                md_to_pdf(md_file, out)
                ok += 1
            except Exception as e:
                print(f"  [FAIL] {md_file.name}: {e}")
                fail += 1
        print(f"\nDone: {ok} succeeded, {fail} failed")

    elif args.input:
        md_file = Path(args.input)
        if not md_file.exists():
            print(f"File not found: {args.input}")
            sys.exit(1)
        out = Path(args.output) if args.output else md_file.with_suffix(".pdf")
        md_to_pdf(md_file, out)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
