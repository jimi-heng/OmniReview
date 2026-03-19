from __future__ import annotations

from pathlib import Path

import markdown
from weasyprint import HTML

from .styles import CSS, MD_EXTENSION_CONFIGS, MD_EXTENSIONS


def md_to_pdf(md_path: Path, pdf_path: Path) -> None:
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

