from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from .orchestrator import run_fulltext
from .pdf import discover_pdfs
from .pico_normalizer import coerce_pico_payload


@dataclass(frozen=True)
class CLIPaths:
    screening_dir: Path
    project_dir: Path


def _default_paths() -> CLIPaths:
    screening_dir = Path(__file__).resolve().parent.parent
    return CLIPaths(screening_dir=screening_dir, project_dir=screening_dir.parent)


def build_arg_parser(paths: CLIPaths) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Full-text screening for systematic reviews",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python Screening/FullTextScreening.py --resources-dir resources/included_papers --project-type PICOS
  python Screening/FullTextScreening.py --project-type PECO --pico-json "{\"p\":\"adults\",\"e\":\"smoking\"}"
        """,
    )

    parser.add_argument(
        "--resources-dir",
        type=Path,
        default=paths.project_dir / "resources" / "included_papers",
        help="Directory containing PDF or TXT files to screen",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=paths.project_dir / "outputs" / "full_text_screening_results.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--project-type",
        type=str,
        default="PICOS",
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="Project type: PICOS/PICO, PECO, or PIRO",
    )
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help='JSON string containing criteria, e.g. \'{"p":"children","i":"iron"}\'',
    )

    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1", help="API base URL")
    parser.add_argument("--model", type=str, default="gpt-4.1", help="Model name to use")
    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1", help="Environment variable name for API key")
    parser.add_argument(
        "--pdf-pages",
        type=str,
        default="all",
        help="Pages to process for PDF inputs: 'all' or '1-3,5' (requires pymupdf)",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="API timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Number of retry attempts on failure")
    parser.add_argument("--retry-delay", type=float, default=3.0, help="Delay between retries in seconds")
    parser.add_argument("--max-concurrency", type=int, default=5, help="Maximum concurrent API requests")
    return parser


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


def _parse_pico_json(value: str) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    try:
        return coerce_pico_payload(parsed)
    except TypeError as exc:
        raise ValueError(f"--pico-json {exc}") from exc


def _write_results_csv(output_csv: Path, papers, results, project_dir: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    paper_by_id = {paper.paper_id: paper for paper in papers}
    fieldnames = ["ID", "Title", "RelativePath", "Decision", "Evidence", "HighlightPath"]

    with output_csv.open("w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            paper = paper_by_id.get(int(result["id"]))
            writer.writerow(
                {
                    "ID": result["id"],
                    "Title": paper.title if paper else "",
                    "RelativePath": _safe_relative(paper.pdf_path, project_dir) if paper else "",
                    "Decision": result["decision"],
                    "Evidence": result["evidence"],
                    "HighlightPath": result["hl_path"] or "",
                }
            )


async def async_main(argv: Optional[List[str]] = None) -> None:
    paths = _default_paths()
    parser = build_arg_parser(paths)
    args = parser.parse_args(argv)

    resources_dir = args.resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"Resources directory not found: {resources_dir}")

    pico_dict = _parse_pico_json(str(args.pico_json))
    papers = discover_pdfs(resources_dir)
    if not papers:
        print(f"No PDF or TXT files found under: {resources_dir}")
        return

    results = await run_fulltext(
        papers,
        pico_dict,
        str(args.project_type),
        config={
            "base_url": str(args.base_url),
            "model": str(args.model),
            "api_key_env": str(args.api_key_env),
            "pdf_pages": str(args.pdf_pages),
            "timeout": float(args.timeout),
            "retries": int(args.retries),
            "retry_delay": float(args.retry_delay),
            "max_concurrency": int(args.max_concurrency),
        },
    )

    _write_results_csv(args.output_csv.resolve(), papers, results, paths.project_dir)

    success_count = sum(1 for result in results if result["decision"] != "Error")
    print("\n" + "=" * 60)
    print("FULL TEXT SCREENING COMPLETE")
    print("=" * 60)
    print(f"Total papers: {len(results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {len(results) - success_count}")
    print(f"CSV output: {args.output_csv}")
    print("=" * 60)


def main(argv: Optional[List[str]] = None) -> None:
    start = time.perf_counter()
    try:
        asyncio.run(async_main(argv))
    finally:
        print(f"\nElapsed: {time.perf_counter() - start:.2f}s")
