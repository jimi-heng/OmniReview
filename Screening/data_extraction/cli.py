from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv

from .http_client import ResponsesAPIClient, ResponsesAPIConfig
from .models import Paper
from .output import csv_to_excel, csv_writer
from .pdf import discover_pdfs, parse_pages_spec
from .service import EnhancedDataExtractor, ExtractionRequest
from .template import read_template_columns


@dataclass(frozen=True)
class CLIPaths:
    screening_dir: Path
    project_dir: Path


def _default_paths() -> CLIPaths:
    screening_dir = Path(__file__).resolve().parent.parent
    return CLIPaths(screening_dir=screening_dir, project_dir=screening_dir.parent)


def build_arg_parser(paths: CLIPaths) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enhanced Data Extraction for Clinical Trial Systematic Reviews",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic extraction
  python EnhancedDataExtraction.py --resources-dir papers/
        """,
    )

    parser.add_argument(
        "--template",
        type=Path,
        default=paths.project_dir / "resources" / "Template for data extraction.xlsx",
        help="Path to Excel template file",
    )
    parser.add_argument(
        "--resources-dir",
        type=Path,
        default=paths.project_dir / "resources" / "included_papers",
        help="Directory containing PDF files to process",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=paths.project_dir / "outputs" / "extracted_data.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--output-xlsx",
        type=Path,
        default=paths.project_dir / "outputs" / "Extracted_Data.xlsx",
        help="Output Excel file path",
    )

    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1", help="API base URL")
    parser.add_argument("--model", type=str, default="gpt-5.2", help="Model name to use")
    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1", help="Environment variable name for API key")

    parser.add_argument(
        "--pdf-pages",
        type=str,
        default="all",
        help="Pages to process: 'all' or '1-3,5' (requires pymupdf)",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="API timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Number of retry attempts on failure")
    parser.add_argument("--retry-delay", type=float, default=3.0, help="Delay between retries in seconds")
    parser.add_argument("--max-concurrency", type=int, default=10, help="Maximum concurrent API requests")
    parser.add_argument(
        "--project-type",
        type=str,
        default="PICOS",
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="Project type: PICOS/PICO (intervention), PECO (exposure), PIRO (diagnostic/prognostic)",
    )
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help='JSON string containing PICO criteria from frontend (e.g., \'{"s":"RCT","p":"children","i":"iron","c":"placebo","o":"hemoglobin"}\')',
    )
    parser.add_argument("--debug-prompt", action="store_true", help="Log first 500 chars of the prompt per paper")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level (DEBUG/INFO/WARNING/ERROR)")
    return parser


async def async_main(argv: Optional[List[str]] = None) -> None:
    paths = _default_paths()
    parser = build_arg_parser(paths)
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO))

    load_dotenv(paths.screening_dir / ".env", override=True)
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing environment variable: {args.api_key_env}")

    pico_dict: Optional[Dict[str, str]]
    if args.pico_json:
        try:
            pico_dict = json.loads(args.pico_json)
            print(f"PICO criteria loaded from frontend: {pico_dict}")
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse --pico-json, using defaults. Error: {e}")
            pico_dict = None
    else:
        pico_dict = None
        print(f"Using default PICO criteria for {args.project_type}")

    template_path = args.template.resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    _, llm_columns = read_template_columns(template_path)
    print(f"Extraction fields: {len(llm_columns)} columns")

    resources_dir = args.resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"Resources directory not found: {resources_dir}")

    papers: List[Paper] = discover_pdfs(resources_dir)
    if not papers:
        print(f"No PDF files found under: {resources_dir}")
        return
    print(f"Found {len(papers)} PDF files to process")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    pages_spec = parse_pages_spec(str(args.pdf_pages))
    endpoint = str(args.base_url).rstrip("/") + "/responses"

    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))
    queue: asyncio.Queue = asyncio.Queue()

    client_cfg = ResponsesAPIConfig(
        endpoint=endpoint,
        api_key=api_key,
        model=str(args.model),
        timeout_s=float(args.timeout),
        retries=int(args.retries),
        retry_delay_s=float(args.retry_delay),
    )

    async with httpx.AsyncClient() as http_client:
        llm_client = ResponsesAPIClient(http_client=http_client, config=client_cfg)
        extractor = EnhancedDataExtractor(
            llm_client=llm_client,
            project_dir=paths.project_dir,
            debug_prompt=bool(args.debug_prompt),
        )

        writer_task = asyncio.create_task(csv_writer(queue, args.output_csv, llm_columns))

        async def handle_paper(paper: Paper):
            async with sem:
                print(f"[Paper {paper.paper_id}] Processing: {paper.title}")
                result = await extractor.extract(
                    paper=paper,
                    request=ExtractionRequest(
                        llm_columns=llm_columns,
                        pages_spec=pages_spec,
                        project_type=str(args.project_type),
                        pico_dict=pico_dict,
                    ),
                )

                if result.error:
                    await queue.put(
                        {
                            "ID": paper.paper_id,
                            "Title": paper.title,
                            "RelativePath": result.relative_path,
                            **{col: "" for col in llm_columns},
                            "Error": result.error,
                        }
                    )
                else:
                    for row in result.value_rows:
                        await queue.put(
                            {
                                "ID": paper.paper_id,
                                "Title": paper.title,
                                "RelativePath": result.relative_path,
                                **row,
                                "Error": "",
                            }
                        )

                status = "SUCCESS" if not result.error else f"ERROR: {result.error[:100]}"
                print(f"[Paper {paper.paper_id}] {status}")
                return result

        try:
            results = await asyncio.gather(*(handle_paper(paper) for paper in papers))
        finally:
            await queue.put(None)
            await writer_task

    csv_to_excel(args.output_csv, args.output_xlsx, template_path)

    success_count = sum(1 for r in results if not r.error)
    fail_count = len(results) - success_count
    total_outcomes = sum(len(r.value_rows) for r in results)

    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Total papers: {len(results)}")
    print(f"Successful: {success_count}")
    print(f"Failed: {fail_count}")
    print(f"Total outcome rows: {total_outcomes}")
    print(f"CSV output: {args.output_csv}")
    print(f"Excel output: {args.output_xlsx}")
    print("=" * 60)


def main(argv: Optional[List[str]] = None) -> None:
    start = time.perf_counter()
    try:
        asyncio.run(async_main(argv))
    finally:
        print(f"\nElapsed: {time.perf_counter() - start:.2f}s")

