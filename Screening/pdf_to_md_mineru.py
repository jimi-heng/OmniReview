from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


def _normalize_md_mode(mode: str) -> str:
    """Normalize common MakeMode aliases to MinerU's expected string values.

    MinerU uses values like 'mm_markdown' / 'nlp_markdown' (see mineru.utils.enum_class.MakeMode).
    Some docs/examples use the enum-style names (e.g. 'MM_MD'), which would otherwise lead to
    no .md output being written.
    """
    mode = (mode or "").strip()
    if not mode:
        return "mm_markdown"

    upper = mode.upper()
    if upper in {"MM_MD", "MM-MD", "MM"}:
        return "mm_markdown"
    if upper in {"NLP_MD", "NLP-MD", "NLP"}:
        return "nlp_markdown"
    if upper in {"CONTENT_LIST", "CONTENT-LIST"}:
        return "content_list"
    if upper in {"CONTENT_LIST_V2", "CONTENT-LIST-V2"}:
        return "content_list_v2"

    return mode


def _discover_pdfs(input_path: Path) -> tuple[Path, list[Path]]:
    """Return (input_root, pdf_paths). input_root is used to preserve relative structure."""
    if input_path.is_file():
        if input_path.suffix.lower() != ".pdf":
            raise ValueError(f"Input file must be a .pdf: {input_path}")
        return input_path.parent, [input_path]

    if input_path.is_dir():
        pdfs = sorted(
            [p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"],
            key=lambda p: str(p).lower(),
        )
        return input_path, pdfs

    raise FileNotFoundError(f"Input path not found: {input_path}")


def _build_output_dir(output_root: Path, input_root: Path, pdf_path: Path) -> Path:
    # Preserve input directory structure and give each PDF its own folder.
    rel_no_suffix = pdf_path.relative_to(input_root).with_suffix("")
    return output_root / rel_no_suffix


def _build_flat_md_path(output_root: Path, input_root: Path, pdf_path: Path) -> Path:
    """Flattened output path (scheme B): output_root/<relative_path_without_ext>.md."""
    return output_root / pdf_path.relative_to(input_root).with_suffix(".md")


def _find_generated_md(raw_out_dir: Path, pdf_stem: str) -> Path | None:
    """Locate the .md produced by MinerU under raw_out_dir (varies by backend/method)."""
    try:
        exact = list(raw_out_dir.rglob(f"{pdf_stem}.md"))
        if exact:
            exact.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return exact[0]
        any_md = list(raw_out_dir.rglob("*.md"))
        if any_md:
            any_md.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return any_md[0]
    except Exception:
        return None
    return None


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Convert PDF(s) to Markdown using MinerU.")
    p.add_argument(
        "--input",
        type=Path,
        default=PROJECT_DIR / "resources",
        help="Path to a PDF file or a directory containing PDFs (recursive). Default: ./resources",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_DIR / "resources_md",
        help="Output root directory. Default: ./resources_md",
    )
    p.add_argument(
        "--raw-output-dir",
        type=Path,
        default=PROJECT_DIR / "outputs" / "mineru_raw",
        help="Where MinerU writes its full raw outputs (md/images/json). Default: ./outputs/mineru_raw",
    )
    p.add_argument(
        "--backend",
        type=str,
        default="hybrid-auto-engine",
        help="MinerU backend, e.g. hybrid-auto-engine, vlm-auto-engine, pipeline, hybrid-http-client, vlm-http-client.",
    )
    p.add_argument(
        "--method",
        type=str,
        default="auto",
        choices=["auto", "ocr", "txt"],
        help="Parse method: auto|ocr|txt.",
    )
    p.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Language code (helps OCR). Example: en, zh, korean, arabic.",
    )
    p.add_argument(
        "--start-page",
        type=int,
        default=0,
        help="0-based start page id. Default: 0",
    )
    p.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="0-based end page id. Default: None (parse to end).",
    )
    p.add_argument(
        "--server-url",
        type=str,
        default=None,
        help="Remote server URL when using *-http-client backends.",
    )
    p.add_argument("--no-formula", action="store_true", help="Disable formula parsing.")
    p.add_argument("--no-table", action="store_true", help="Disable table parsing.")
    p.add_argument(
        "--md-mode",
        type=str,
        default="mm_markdown",
        help="MinerU make mode (f_make_md_mode). Use mm_markdown (default) or nlp_markdown. "
             "Enum-like aliases like MM_MD / NLP_MD are also accepted.",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output .md if present.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    input_path = args.input.expanduser()
    output_root = args.output_dir.expanduser()
    raw_root = args.raw_output_dir.expanduser()

    if args.start_page is not None and args.start_page < 0:
        print("--start-page must be >= 0", file=sys.stderr)
        return 2
    if args.end_page is not None and args.end_page < 0:
        print("--end-page must be >= 0 (or omit it)", file=sys.stderr)
        return 2
    if args.end_page is not None and args.end_page < args.start_page:
        print("--end-page must be >= --start-page", file=sys.stderr)
        return 2

    try:
        from mineru.cli.common import do_parse, read_fn
    except Exception as e:
        print("ERROR: MinerU is not installed (import failed).", file=sys.stderr)
        print('Install: uv pip install -U "mineru[all]"', file=sys.stderr)
        print(f"Details: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    try:
        input_root, pdf_paths = _discover_pdfs(input_path)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if not pdf_paths:
        print(f"No PDFs found under: {input_path}", file=sys.stderr)
        return 1

    output_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    # If output is inside the input directory, avoid re-processing PDFs under the output tree.
    if input_path.is_dir():
        out_abs = output_root.resolve(strict=False)
        raw_abs = raw_root.resolve(strict=False)
        pdf_paths = [
            p
            for p in pdf_paths
            if not p.resolve(strict=False).is_relative_to(out_abs)
            and not p.resolve(strict=False).is_relative_to(raw_abs)
        ]

    md_mode = _normalize_md_mode(args.md_mode)
    if md_mode not in {"mm_markdown", "nlp_markdown"}:
        print(
            f"ERROR: --md-mode must be mm_markdown or nlp_markdown for Markdown output. Got: {args.md_mode!r}",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for pdf_path in pdf_paths:
        raw_out_dir = _build_output_dir(raw_root, input_root, pdf_path)
        flat_md = _build_flat_md_path(output_root, input_root, pdf_path)

        if flat_md.exists() and not args.overwrite:
            print(f"SKIP (exists): {flat_md}")
            continue

        raw_out_dir.mkdir(parents=True, exist_ok=True)
        flat_md.parent.mkdir(parents=True, exist_ok=True)

        # If a previous run already produced the raw markdown, just flatten/copy it.
        if not args.overwrite:
            existing_md = _find_generated_md(raw_out_dir, pdf_path.stem)
            if existing_md:
                shutil.copyfile(existing_md, flat_md)
                print(f"REUSE: {pdf_path}")
                print(f"  RAW:  {existing_md}")
                print(f"  FLAT: {flat_md}")
                continue

        print(f"CONVERT: {pdf_path}")

        try:
            pdf_bytes = read_fn(pdf_path)

            do_parse(
                output_dir=str(raw_out_dir),
                pdf_file_names=[pdf_path.stem],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[args.lang],
                backend=args.backend,
                parse_method=args.method,
                formula_enable=not args.no_formula,
                table_enable=not args.no_table,
                server_url=args.server_url,
                f_draw_layout_bbox=False,
                f_draw_span_bbox=False,
                f_dump_md=True,
                f_dump_middle_json=False,
                f_dump_model_output=False,
                f_dump_orig_pdf=False,
                f_dump_content_list=False,
                f_make_md_mode=md_mode,
                start_page_id=args.start_page,
                end_page_id=args.end_page,
            )

            generated_md = _find_generated_md(raw_out_dir, pdf_path.stem)
            if not generated_md:
                print(
                    f"WARNING: MinerU did not generate a .md under: {raw_out_dir} (md-mode={md_mode!r})",
                    file=sys.stderr,
                )
                continue

            shutil.copyfile(generated_md, flat_md)
            print(f"  RAW:  {generated_md}")
            print(f"  FLAT: {flat_md}")

        except Exception as e:
            failures += 1
            print(f"FAILED: {pdf_path}", file=sys.stderr)
            print(f"  {type(e).__name__}: {e}", file=sys.stderr)

    if failures:
        print(f"Done with {failures} failure(s).", file=sys.stderr)
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
