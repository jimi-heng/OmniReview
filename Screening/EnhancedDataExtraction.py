#!/usr/bin/env python3
"""
Enhanced Data Extraction Script for Clinical Trial Systematic Reviews
=====================================================================

This script extracts data from clinical trial PDFs for systematic reviews.

Key Features:
- PICO-guided extraction (embedded in prompt template)
- Async concurrent processing for multiple papers
- PDF Base64 upload for direct processing
- Robust JSON parsing with multiple fallback strategies
- Excel template integration
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import csv
import json
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook

# Try importing PyMuPDF for PDF processing
try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


# ============================================================================
# Constants and Configuration
# ============================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# Default prompt templates
DEFAULT_SYSTEM_PROMPT = """You are an expert medical data extractor for systematic reviews.

CRITICAL OUTPUT FORMAT — you MUST follow this exactly:
- Return ONLY raw JSON. No markdown fences, no explanation, no preamble.
- The JSON must be an array of objects: [ { ... }, { ... } ]
- EVERY field MUST be a nested object with exactly two keys "value" and "evidence":
  {"value": "<extracted data>", "evidence": "<verbatim quote from PDF>"}
- NEVER return a flat string like "Age": "6.5". ALWAYS use the nested format:
  "Age": {"value": "6.5", "evidence": "The median age was 6.5 years (IQR 4-8)."}
- The "evidence" MUST be the exact sentence or phrase copied verbatim from the PDF.
- If a field is not found: {"value": "Not Reported", "evidence": ""}

Extraction rules:
- Extract strictly from visible PDF content. Do not hallucinate or infer.
- For numbers (Mean, SD, Events, Total): extract exact reported values as strings.
- Multi-arm mapping: Arm1 = intervention, Arm2 = comparator/control.
- Multiple outcomes: return one JSON object per outcome row, duplicating study metadata.
"""

DEFAULT_USER_PROMPT_TEMPLATE = """Extract the following data fields from the attached PDF.

Target PICO Criteria for this Evaluation:
- Population (P): 铁缺乏但尚未贫血的儿童(0-6岁), 合并疾病?
- Intervention (I): 铁剂治疗(每日2 mg/kg元素铁的口服铁剂治疗,疗程为12周),剂量,疗程
- Comparison (C): 不进行铁剂治疗
- Outcome (O): Critical:血色素水平, 贫血的发生率, 生长发育指标; Important: 安全性指标：胃肠道反应、食欲下降, 神经认知发育, 肠道菌群, 感染性疾病患病率
- Extra requirements: Study design: SR、RCT、观察性研究

Data fields to extract:
{columns_section}

MANDATORY OUTPUT FORMAT:
Return a JSON array. EVERY field must use the nested {{"value": "...", "evidence": "..."}} format.
The "evidence" is the verbatim sentence from the PDF that supports the value.

Paper ID: {paper_id}
"""


# ============================================================================
# Data Classes
# ============================================================================

@dataclass(frozen=True)
class Paper:
    """Paper metadata for processing."""
    paper_id: int
    path: Path
    title: str


@dataclass
class ExtractionResult:
    """Result of extraction for a single paper."""
    paper_id: int
    title: str
    relative_path: str
    value_rows: List[Dict[str, str]] = field(default_factory=list)
    evidence_rows: List[Dict[str, str]] = field(default_factory=list)
    error: str = ""


# ============================================================================
# PDF Processing Utilities
# ============================================================================

def load_pdf_bytes(pdf_path: Path, pages: Optional[List[int]] = None) -> bytes:
    """Load PDF bytes, optionally extracting specific pages."""
    data = pdf_path.read_bytes()
    if pages is None:
        return data

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for page extraction. Install `pymupdf`.")

    with fitz.open(stream=data, filetype="pdf") as src:
        page_count = src.page_count
        selected = [p for p in pages if 1 <= p <= page_count]
        if not selected:
            return data

        out = fitz.open()
        for p in selected:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        return out.tobytes()


def parse_pages_spec(spec: str) -> Optional[List[int]]:
    """Parse page specification string into list of page numbers."""
    s = (spec or "").strip().lower()
    if s in {"all", "*"}:
        return None

    pages: set[int] = set()
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
            p = int(part)
            if p > 0:
                pages.add(p)
    return sorted(pages) if pages else None


def generate_columns_section(llm_columns: List[str]) -> str:
    """Generate columns description section for prompt based on template columns."""
    if not llm_columns:
        return "No specific columns defined. Extract all relevant data."

    # 将列名格式化为简洁的列表
    columns_list = ", ".join(llm_columns)
    return f"- {columns_list}"


# ============================================================================
# Template Processing
# ============================================================================

def read_template_columns(template_path: Path) -> Tuple[List[str], List[str]]:
    """Read column names from all sheets in Excel template."""
    wb = load_workbook(template_path, read_only=True)
    try:
        all_columns = []
        seen_columns = set()  # 避免重复列名

        # 遍历所有工作表
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if not header_row:
                continue

            for value in header_row:
                if value is None:
                    continue
                col = str(value).strip()
                if col and col not in seen_columns:
                    seen_columns.add(col)
                    all_columns.append(col)

        if not all_columns:
            raise ValueError("No columns found in any sheet")

        metadata_fields = {"Rayyan_ID", "Title", "Abstract", "Full_Text", "Extractor", "Checker"}
        llm_columns = [c for c in all_columns if c not in metadata_fields]
        return all_columns, llm_columns
    finally:
        wb.close()


# ============================================================================
# Robust JSON Parsing
# ============================================================================

class RobustJSONParser:
    """Robust JSON parser with multiple fallback strategies."""

    @staticmethod
    def parse(text: str, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """
        Parse JSON from LLM response with multiple fallback strategies.

        Returns:
            Tuple of (value_rows, evidence_rows)
        """
        if not text or not text.strip():
            raise ValueError("Empty model output")

        # Strategy 1: Try direct parsing
        parsed = RobustJSONParser._try_direct_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        # Strategy 2: Extract from markdown code blocks
        parsed = RobustJSONParser._try_markdown_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        # Strategy 3: Find JSON by braces
        parsed = RobustJSONParser._try_brace_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        # Strategy 4: Repair truncated JSON
        parsed = RobustJSONParser._try_repair_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        raise ValueError("No valid JSON found in response")

    @staticmethod
    def _try_direct_parse(text: str) -> Optional[Any]:
        """Try direct JSON parsing with preprocessing."""
        stripped = text.strip()
        # Remove markdown fences
        if stripped.startswith("```json"):
            stripped = stripped[7:].strip()
        elif stripped.startswith("```"):
            stripped = stripped[3:].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()

        try:
            return json.loads(stripped, strict=False)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _try_markdown_parse(text: str) -> Optional[Any]:
        """Extract JSON from markdown code blocks."""
        patterns = [
            r"```json\s*\n(.*?)\n```",
            r"```\s*\n(.*?)\n```",
        ]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match, strict=False)
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _try_brace_parse(text: str) -> Optional[Any]:
        """Find JSON by matching braces."""
        start_match = re.search(r"[\[{]", text)
        if not start_match:
            return None

        start = start_match.start()
        end_arr = text.rfind("]")
        end_obj = text.rfind("}")
        end = max(end_arr, end_obj)

        if end < start:
            return None

        candidate = text[start : end + 1]
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _try_repair_parse(text: str) -> Optional[Any]:
        """Attempt to repair and parse truncated JSON."""
        stripped = text.strip()
        first_brace = stripped.find("{")
        if first_brace < 0:
            return None

        json_text = stripped[first_brace:]
        repaired = RobustJSONParser._repair_truncated(json_text)
        if repaired is not None:
            try:
                return json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _repair_truncated(text: str) -> Optional[str]:
        """Repair truncated JSON by closing unclosed braces/brackets."""
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False

        for char in text:
            if escape_next:
                escape_next = False
                continue
            if char == "\\" and in_string:
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                open_braces += 1
            elif char == "}":
                open_braces -= 1
            elif char == "[":
                open_brackets += 1
            elif char == "]":
                open_brackets -= 1

        if open_braces <= 0 and open_brackets <= 0:
            return text

        repaired = text.rstrip()
        if in_string:
            last_quote = repaired.rfind('"')
            if last_quote > 0:
                repaired = repaired[: last_quote + 1]

        repaired = repaired.rstrip().rstrip(",")
        repaired += "]" * max(0, open_brackets)
        repaired += "}" * max(0, open_braces)

        return repaired

    @staticmethod
    def _process_parsed(
        parsed: Any, columns: List[str]
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Process parsed JSON into value and evidence rows."""
        if isinstance(parsed, dict):
            rows = [parsed]
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ValueError("JSON root must be object or array")

        value_rows = []
        evidence_rows = []

        for item in rows:
            if not isinstance(item, dict):
                continue
            values, evidences = RobustJSONParser._split_nested_row(item, columns)
            value_rows.append(values)
            evidence_rows.append(evidences)

        if not value_rows:
            raise ValueError("No valid row objects in JSON")

        return value_rows, evidence_rows

    @staticmethod
    def _split_nested_row(
        row: Dict[str, Any], columns: List[str]
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """Split nested {col: {value, evidence}} row into separate dicts."""
        values = {}
        evidences = {}

        for col in columns:
            cell = row.get(col, "Not Reported")
            if isinstance(cell, dict):
                values[col] = RobustJSONParser._normalize_value(cell.get("value", "Not Reported"))
                ev = cell.get("evidence", "")
                if isinstance(ev, str) and ev.strip():
                    evidences[col] = ev.strip()
            else:
                values[col] = RobustJSONParser._normalize_value(cell)

        return values, evidences

    @staticmethod
    def _normalize_value(value: Any) -> str:
        """Normalize value to string."""
        if value is None:
            return "Not Reported"
        if isinstance(value, str):
            return value.strip() if value.strip() else "Not Reported"
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)


# ============================================================================
# Async HTTP Client
# ============================================================================

async def post_with_auth_fallback(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    """Post with fallback authentication methods."""
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403):
        return r1

    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)


async def call_with_retry(coro_func, *args, retries: int, delay_s: float):
    """Call async function with retry on failure."""
    last_exc = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry failed")


def extract_output_text(resp_json: Dict[str, Any]) -> str:
    """Extract output text from API response."""
    out_parts = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    out_parts.append(text)

    if out_parts:
        return "\n".join(out_parts)

    for key in ("output_text", "text"):
        value = resp_json.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


# ============================================================================
# Core Extraction Logic
# ============================================================================

async def extract_from_paper(
    client: httpx.AsyncClient,
    paper: Paper,
    llm_columns: List[str],
    endpoint: str,
    api_key: str,
    model: str,
    timeout_s: float,
    retries: int,
    retry_delay: float,
    pages_spec: Optional[List[int]],
) -> ExtractionResult:
    """Extract data from a paper."""
    base_error = ""
    value_rows = []
    evidence_rows = []

    try:
        pdf_bytes = load_pdf_bytes(paper.path, pages_spec)

        # Build prompt
        columns_section = generate_columns_section(llm_columns)

        user_prompt = DEFAULT_USER_PROMPT_TEMPLATE.format(
            columns_section=columns_section,
            paper_id=paper.paper_id,
        )

        full_prompt = DEFAULT_SYSTEM_PROMPT + "\n\n" + user_prompt

        # Build payload with PDF Base64 upload
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        payload = {
            "model": model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": paper.path.name,
                            "file_data": f"data:application/pdf;base64,{b64}",
                        },
                        {"type": "input_text", "text": full_prompt},
                    ],
                }
            ],
        }

        resp = await call_with_retry(
            post_with_auth_fallback,
            client,
            endpoint,
            api_key,
            payload,
            timeout_s,
            retries=retries,
            delay_s=retry_delay,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        text = extract_output_text(data)

        value_rows, evidence_rows = RobustJSONParser.parse(text, llm_columns)

    except Exception as e:
        base_error = str(e)
        traceback.print_exc()

    return ExtractionResult(
        paper_id=paper.paper_id,
        title=paper.title,
        relative_path=str(paper.path.relative_to(PROJECT_DIR)) if paper.path.is_relative_to(PROJECT_DIR) else str(paper.path),
        value_rows=value_rows,
        evidence_rows=evidence_rows,
        error=base_error,
    )


# ============================================================================
# CSV/Excel Output
# ============================================================================

async def csv_writer(
    queue: asyncio.Queue,
    output_csv: Path,
    columns: List[str],
) -> None:
    """Write extraction results to CSV asynchronously."""
    fieldnames = ["ID", "Title", "RelativePath"] + columns + ["Error"]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        f.flush()

        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                writer.writerow(item)
                f.flush()
            finally:
                queue.task_done()


def csv_to_excel(csv_path: Path, xlsx_path: Path, template_path: Path) -> None:
    """Convert CSV to Excel with template-based column ordering."""
    template_columns, _ = read_template_columns(template_path)
    metadata_fields = {"Rayyan_ID", "Title", "Abstract", "Full_Text", "Extractor", "Checker"}
    preferred = ["ID", "Title", "RelativePath"] + [c for c in template_columns if c not in metadata_fields] + ["Error"]

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        csv_headers = list(reader.fieldnames or [])
        ordered_headers = [h for h in preferred if h in csv_headers]
        ordered_headers.extend([h for h in csv_headers if h not in ordered_headers])

        wb = Workbook()
        ws = wb.active
        ws.title = "baseline characteristics"
        ws.append(ordered_headers)
        for row in reader:
            ws.append([row.get(col, "") for col in ordered_headers])

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)


# ============================================================================
# Paper Discovery
# ============================================================================

def discover_pdfs(resources_dir: Path) -> List[Paper]:
    """Find all PDF files in resources directory."""
    pdfs = sorted(
        [p for p in resources_dir.rglob("*.pdf") if p.is_file()],
        key=lambda p: str(p).lower()
    )
    out = []
    for i, path in enumerate(pdfs, start=1):
        out.append(Paper(paper_id=i, path=path.resolve(), title=path.stem))
    return out


# ============================================================================
# Main Entry Point
# ============================================================================

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enhanced Data Extraction for Clinical Trial Systematic Reviews",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic extraction
  python EnhancedDataExtraction.py --resources-dir papers/
        """,
    )

    # Input/Output arguments
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_DIR / "resources" / "Template for data extraction.xlsx",
        help="Path to Excel template file",
    )
    parser.add_argument(
        "--resources-dir",
        type=Path,
        default=PROJECT_DIR / "resources" / "included_papers",
        help="Directory containing PDF files to process",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_DIR / "outputs" / "extracted_data.csv",
        help="Output CSV file path",
    )
    parser.add_argument(
        "--output-xlsx",
        type=Path,
        default=PROJECT_DIR / "outputs" / "Extracted_Data.xlsx",
        help="Output Excel file path",
    )

    # API arguments
    parser.add_argument(
        "--base-url",
        type=str,
        default="https://www.dmxapi.cn/v1",
        help="API base URL",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gpt-5.2",
        help="Model name to use",
    )
    parser.add_argument(
        "--api-key-env",
        type=str,
        default="DMX_API_KEY_1",
        help="Environment variable name for API key",
    )

    # Processing arguments
    parser.add_argument(
        "--pdf-pages",
        type=str,
        default="all",
        help="Pages to process: 'all' or '1-3,5' (requires pymupdf)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="API timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retry attempts on failure",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=3.0,
        help="Delay between retries in seconds",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=10,
        help="Maximum concurrent API requests",
    )

    args = parser.parse_args()

    # Load environment variables
    load_dotenv(SCRIPT_DIR / ".env", override=True)
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing environment variable: {args.api_key_env}")

    # Load template columns
    template_path = args.template.resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    _, llm_columns = read_template_columns(template_path)
    print(f"Extraction fields: {len(llm_columns)} columns")

    # Discover PDFs
    resources_dir = args.resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"Resources directory not found: {resources_dir}")

    papers = discover_pdfs(resources_dir)
    if not papers:
        print(f"No PDF files found under: {resources_dir}")
        return

    print(f"Found {len(papers)} PDF files to process")

    # Prepare output directory
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    pages_spec = parse_pages_spec(str(args.pdf_pages))

    # Setup concurrency
    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))
    endpoint = args.base_url.rstrip("/") + "/responses"

    # Results queue
    queue: asyncio.Queue = asyncio.Queue()

    async with httpx.AsyncClient() as client:
        writer_task = asyncio.create_task(csv_writer(queue, args.output_csv, llm_columns))

        async def handle_paper(paper: Paper) -> ExtractionResult:
            async with sem:
                print(f"[Paper {paper.paper_id}] Processing: {paper.title}")
                result = await extract_from_paper(
                    client=client,
                    paper=paper,
                    llm_columns=llm_columns,
                    endpoint=endpoint,
                    api_key=api_key,
                    model=args.model,
                    timeout_s=float(args.timeout),
                    retries=int(args.retries),
                    retry_delay=float(args.retry_delay),
                    pages_spec=pages_spec,
                )

                # Write to CSV
                if result.error:
                    await queue.put({
                        "ID": paper.paper_id,
                        "Title": paper.title,
                        "RelativePath": result.relative_path,
                        **{col: "" for col in llm_columns},
                        "Error": result.error,
                    })
                else:
                    for row in result.value_rows:
                        await queue.put({
                            "ID": paper.paper_id,
                            "Title": paper.title,
                            "RelativePath": result.relative_path,
                            **row,
                            "Error": "",
                        })

                status = "SUCCESS" if not result.error else f"ERROR: {result.error[:100]}"
                print(f"[Paper {paper.paper_id}] {status}")

                return result

        try:
            results = await asyncio.gather(*(handle_paper(paper) for paper in papers))
        finally:
            await queue.put(None)
            await writer_task

    # Convert to Excel
    csv_to_excel(args.output_csv, args.output_xlsx, template_path)

    # Print summary
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


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        asyncio.run(main())
    finally:
        print(f"\nElapsed: {time.perf_counter() - start:.2f}s")