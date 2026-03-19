from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convert import md_to_pdf


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Markdown to PDF converter")
    parser.add_argument("input", nargs="?", help="Input .md file path")
    parser.add_argument("output", nargs="?", help="Output .pdf file path (optional)")
    parser.add_argument("--dir", help="Batch convert all .md files in the directory")
    args = parser.parse_args(argv)

    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"Directory not found: {args.dir}")
            return 2
        md_files = sorted(dir_path.glob("*.md"))
        if not md_files:
            print(f"No .md files found in {dir_path}")
            return 0
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
        return 0 if fail == 0 else 1

    if args.input:
        md_file = Path(args.input)
        if not md_file.exists():
            print(f"File not found: {args.input}")
            return 2
        out = Path(args.output) if args.output else md_file.with_suffix(".pdf")
        md_to_pdf(md_file, out)
        return 0

    parser.print_help()
    return 0

