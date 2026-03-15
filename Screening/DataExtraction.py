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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from openpyxl import Workbook, load_workbook

try:
    from TextHighlight import highlight_pdf
except Exception:  # pragma: no cover
    from Screening.TextHighlight import highlight_pdf

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


SYSTEM_PROMPT = """
You are an expert medical data extractor for systematic reviews.

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

USER_PROMPT_TEMPLATE = """
Extract the following data fields from the attached PDF.
Process systematically through these groups:

== Group 1: Study Metadata ==
Year, Study_ID, Trial_Number, Study_Name, Country, Number_of_centers

== Group 2: Study Design ==
Study_Inclusion, Exclusion_Criteria, Diagnosis

== Group 3: Population ==
Sample_Size, Age, Gender, Follow_up

== Group 4: Interventions ==
Arm_1_Specific_Regimens, Arm1_Drugs, Arm2_Specific_Regimens, Arm2_Drugs

== Group 5: Outcomes (one JSON object per outcome) ==
Outcome_Reproted, Name_of_Outcome, Definition, Measurement_Time_
Arm1_Mean, Arm1_SD, Arm1_Total, Arm2_Mean, Arm2_SD, Arm2_Total
Arm1_Events, Arm1_Total, Arm2_Events, Arm2_Total

== Group 6: Notes ==
Note

MANDATORY OUTPUT FORMAT:
Return a JSON array. EVERY field must use the nested {"value": "...", "evidence": "..."} format.
The "evidence" is the verbatim sentence from the PDF that supports the value.

COMPLETE EXAMPLE (showing the REQUIRED nested format for ALL fields):
[
  {
    "Year": {"value": "2019", "evidence": "This randomized controlled trial was conducted between January and December 2019."},
    "Study_ID": {"value": "Not Reported", "evidence": ""},
    "Trial_Number": {"value": "NCT01234567", "evidence": "The trial was registered at ClinicalTrials.gov (NCT01234567)."},
    "Study_Name": {"value": "IRON-KIDS", "evidence": "The IRON-KIDS study was a double-blind placebo-controlled trial."},
    "Country": {"value": "Indonesia", "evidence": "The study was conducted in rural Indonesia."},
    "Number_of_centers": {"value": "1", "evidence": "Participants were recruited from a single health center."},
    "Study_Inclusion": {"value": "Healthy infants aged 6 months", "evidence": "Inclusion criteria were healthy singleton infants who had not passed 6 months of age."},
    "Exclusion_Criteria": {"value": "Not Reported", "evidence": ""},
    "Diagnosis": {"value": "Iron-replete infants", "evidence": "All enrolled infants were confirmed iron-replete at baseline."},
    "Sample_Size": {"value": "154", "evidence": "A total of 154 infants were enrolled in the study."},
    "Age": {"value": "6 months", "evidence": "Infants were enrolled at 6 months of age."},
    "Gender": {"value": "56% female", "evidence": "Of the 80 infants in the iron group, 45 (56%) were girls."},
    "Follow_up": {"value": "6 months", "evidence": "Children were followed from 6 to 12 months of age."},
    "Arm_1_Specific_Regimens": {"value": "10 mg iron daily", "evidence": "The intervention group received a daily dose of 10 mg of iron as ferrous sulphate."},
    "Arm1_Drugs": {"value": "Ferrous sulphate", "evidence": "Iron was provided as ferrous sulphate in sweet-tasting syrup."},
    "Arm2_Specific_Regimens": {"value": "Placebo syrup daily", "evidence": "The control group received placebo syrup identical in appearance."},
    "Arm2_Drugs": {"value": "Placebo", "evidence": "The control group received placebo syrup identical in appearance."},
    "Outcome_Reproted": {"value": "Weight-for-age z-score", "evidence": "The primary outcome was weight-for-age z-score (WAZ) at 12 months."},
    "Name_of_Outcome": {"value": "WAZ at 12 months", "evidence": "The primary outcome was weight-for-age z-score (WAZ) at 12 months."},
    "Definition": {"value": "WAZ compared to CDC reference", "evidence": "Z-scores were calculated using the CDC 2000 growth reference."},
    "Measurement_Time_": {"value": "12 months", "evidence": "Outcomes were measured at 12 months of age."},
    "Arm1_Mean": {"value": "-1.99", "evidence": "The mean WAZ in the iron group was -1.99 (SD 1.02)."},
    "Arm1_SD": {"value": "1.02", "evidence": "The mean WAZ in the iron group was -1.99 (SD 1.02)."},
    "Arm1_Total": {"value": "80", "evidence": "80 infants were in the iron-supplemented group."},
    "Arm2_Mean": {"value": "-1.58", "evidence": "The mean WAZ in the control group was -1.58 (SD 1.13)."},
    "Arm2_SD": {"value": "1.13", "evidence": "The mean WAZ in the control group was -1.58 (SD 1.13)."},
    "Arm2_Total": {"value": "74", "evidence": "74 infants were in the non-supplemented group."},
    "Arm1_Events": {"value": "Not Reported", "evidence": ""},
    "Arm1_Total": {"value": "80", "evidence": "80 infants were in the iron-supplemented group."},
    "Arm2_Events": {"value": "Not Reported", "evidence": ""},
    "Arm2_Total": {"value": "74", "evidence": "74 infants were in the non-supplemented group."},
    "Note": {"value": "Iron-replete subgroup analysis", "evidence": "This analysis focused on the iron-replete subgroup."}
  }
]

Paper ID: {paper_id}
"""


def _read_template_columns(template_path: Path) -> tuple[list[str], list[str]]:
    wb = load_workbook(template_path, read_only=True)
    try:
        if "baseline characteristics" not in wb.sheetnames:
            raise KeyError("Missing sheet: baseline characteristics")
        ws = wb["baseline characteristics"]
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not header_row:
            raise ValueError("Template header row is empty")

        all_columns = []
        for value in header_row:
            if value is None:
                continue
            col = str(value).strip()
            if col:
                all_columns.append(col)

        # Auto-filled or non-LLM metadata fields.
        metadata_fields = {"Rayyan_ID", "Title", "Abstract", "Full_Text", "Extractor", "Checker"}
        llm_columns = [c for c in all_columns if c not in metadata_fields]
        return all_columns, llm_columns
    finally:
        wb.close()


def _parse_pages_spec(spec: str) -> Optional[list[int]]:
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
    return sorted(pages)


def _load_pdf_bytes(pdf_path: Path, pages: Optional[list[int]]) -> bytes:
    data = pdf_path.read_bytes()
    if pages is None:
        return data

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for --pdf-pages. Install `pymupdf`.")

    with fitz.open(stream=data, filetype="pdf") as src:
        page_count = src.page_count
        selected = [p for p in pages if 1 <= p <= page_count]
        if not selected:
            return data

        out = fitz.open()
        for p in selected:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        return out.tobytes()


def _extract_output_text(resp_json: dict[str, Any]) -> str:
    out_parts: list[str] = []
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


async def _post_with_auth_fallback(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403):
        return r1

    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)


async def _call_with_retry(coro_func, *args, retries: int, delay_s: float):
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            await asyncio.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retry failed")  # pragma: no cover


@dataclass(frozen=True)
class Paper:
    paper_id: int
    path: Path
    title: str


def _discover_pdfs(resources_dir: Path) -> list[Paper]:
    pdfs = sorted([p for p in resources_dir.rglob("*.pdf") if p.is_file()], key=lambda p: str(p).lower())
    out: list[Paper] = []
    for i, path in enumerate(pdfs, start=1):
        out.append(Paper(paper_id=i, path=path.resolve(), title=path.stem))
    return out


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


def _normalize_value(value: Any) -> str:
    if value is None:
        return "Not Reported"
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else "Not Reported"
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _split_nested_row(
    row: dict[str, Any], columns: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Split a nested {col: {value, evidence}} row into (values_dict, evidences_dict)."""
    values: dict[str, str] = {}
    evidences: dict[str, str] = {}
    for col in columns:
        cell = row.get(col, "Not Reported")
        if isinstance(cell, dict):
            values[col] = _normalize_value(cell.get("value", "Not Reported"))
            ev = cell.get("evidence", "")
            if isinstance(ev, str) and ev.strip():
                evidences[col] = ev.strip()
            continue

        # LLM fallback: flat key-value output with no nested evidence object.
        values[col] = _normalize_value(cell)
    return values, evidences


def _parse_extraction_json(
    text: str, columns: list[str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not text or not text.strip():
        raise ValueError("empty model output")

    start_match = re.search(r"[\[{]", text)
    if not start_match:
        raise ValueError("no JSON start token found")
    start = start_match.start()

    end_arr = text.rfind("]")
    end_obj = text.rfind("}")
    end = max(end_arr, end_obj)
    if end < start:
        raise ValueError("no JSON end token found")

    candidate = text[start : end + 1]
    # strict=False allows control characters (e.g. literal newlines) inside JSON strings,
    # which LLMs frequently produce in long evidence quotes.
    parsed = json.loads(candidate, strict=False)

    if isinstance(parsed, dict):
        rows: list[Any] = [parsed]
    elif isinstance(parsed, list):
        rows = parsed
    else:
        raise ValueError("JSON root must be object or array")

    value_rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        values, evidences = _split_nested_row(item, columns)
        value_rows.append(values)
        evidence_rows.append(evidences)

    if not value_rows:
        raise ValueError("no valid row objects in JSON")
    return value_rows, evidence_rows


def _build_highlight_evidences(evidence_rows: list[dict[str, str]]) -> dict[str, str]:
    """
    Merge evidence dicts from all outcome rows into a single dict for highlighting.
    Uses a single generic key prefix so all highlights share one color.
    Deduplicates repeated evidence across rows.
    """
    result: dict[str, str] = {}
    seen_texts: set[str] = set()
    count = 0

    for ev_dict in evidence_rows:
        for field, text in ev_dict.items():
            if not text.strip():
                continue
            norm = " ".join(text.lower().split())
            if norm in seen_texts:
                continue
            seen_texts.add(norm)
            count += 1
            result[f"Evidence_{count}"] = text
    return result


def _blank_llm_values(columns: list[str]) -> dict[str, str]:
    return {col: "" for col in columns}


async def _csv_writer(
    queue: "asyncio.Queue[dict[str, Any] | None]",
    output_csv: Path,
    columns: list[str],
) -> None:
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


def _csv_to_excel(csv_path: Path, xlsx_path: Path, template_path: Path) -> None:
    template_columns, _ = _read_template_columns(template_path)
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="Extract structured data from PDFs via DMX Responses API")
    parser.add_argument(
        "--template",
        type=Path,
        default=PROJECT_DIR / "resources" / "Templete for data extraction.xlsx",
    )
    parser.add_argument(
        "--resources-dir",
        type=Path,
        default=PROJECT_DIR / "resources" / "included_papers",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_DIR / "outputs" / "extracted_data.csv",
    )
    parser.add_argument(
        "--output-xlsx",
        type=Path,
        default=PROJECT_DIR / "outputs" / "Extracted_Data.xlsx",
    )
    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1")
    parser.add_argument("--model", type=str, default="gpt-5.1")
    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1")
    parser.add_argument("--pdf-pages", type=str, default="all", help="e.g. all or 1-3,5 (requires pymupdf)")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--max-concurrency", type=int, default=10)
    parser.add_argument("--no-highlight", action="store_true", help="Skip PDF highlighting")
    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR / ".env", override=True)
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing env var in Screening/.env: {args.api_key_env}")

    template_path = args.template.resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"template not found: {template_path}")
    _, llm_columns = _read_template_columns(template_path)

    endpoint = args.base_url.rstrip("/") + "/responses"
    resources_dir = args.resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources-dir not found: {resources_dir}")

    papers = _discover_pdfs(resources_dir)
    if not papers:
        print(f"No PDF files found under: {resources_dir}")

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    pages = _parse_pages_spec(str(args.pdf_pages))
    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    async with httpx.AsyncClient() as client:
        writer_task = asyncio.create_task(_csv_writer(queue, args.output_csv, llm_columns))

        async def handle(paper: Paper) -> None:
            base_row = {
                "ID": paper.paper_id,
                "Title": paper.title,
                "RelativePath": _safe_relative(paper.path, PROJECT_DIR),
            }
            async with sem:
                try:
                    prompt = SYSTEM_PROMPT + "\n\n" + USER_PROMPT_TEMPLATE.replace("{paper_id}", str(paper.paper_id))
                    pdf_bytes = _load_pdf_bytes(paper.path, pages)
                    b64 = base64.b64encode(pdf_bytes).decode("ascii")
                    payload = {
                        "model": args.model,
                        "input": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_file",
                                        "filename": paper.path.name,
                                        "file_data": f"data:application/pdf;base64,{b64}",
                                    },
                                    {"type": "input_text", "text": prompt},
                                ],
                            }
                        ],
                    }

                    resp = await _call_with_retry(
                        _post_with_auth_fallback,
                        client,
                        endpoint,
                        api_key,
                        payload,
                        float(args.timeout),
                        retries=int(args.retries),
                        delay_s=float(args.retry_delay),
                    )

                    if resp.status_code != 200:
                        print(f"[Paper {paper.paper_id}] HTTP {resp.status_code}: {resp.text[:200]}")
                        await queue.put(
                            {
                                **base_row,
                                **_blank_llm_values(llm_columns),
                                "Error": f"HTTP {resp.status_code}",
                            }
                        )
                        return

                    data = resp.json()
                    text = _extract_output_text(data)
                    try:
                        value_rows, evidence_rows = _parse_extraction_json(text, llm_columns)
                    except (json.JSONDecodeError, ValueError) as exc:
                        print(f"[Paper {paper.paper_id}] JSON Parse Error: {exc!r}")
                        if text:
                            print(f"[Paper {paper.paper_id}] Raw output snippet: {text[:500]}")
                        await queue.put(
                            {
                                **base_row,
                                **_blank_llm_values(llm_columns),
                                "Error": "JSON Parse Error",
                            }
                        )
                        return

                    if not args.no_highlight:
                        merged_evidences = _build_highlight_evidences(evidence_rows)
                        ev_count = sum(len(d) for d in evidence_rows)
                        print(f"[Paper {paper.paper_id}] Evidences extracted: {ev_count}, unique for highlight: {len(merged_evidences)}")
                        if merged_evidences:
                            try:
                                hl_dir = PROJECT_DIR / "outputs" / "highlighted_pdfs"
                                hl_dir.mkdir(parents=True, exist_ok=True)
                                out_pdf = hl_dir / f"HL_{paper.path.name}"
                                loop = asyncio.get_running_loop()
                                await loop.run_in_executor(
                                    None, highlight_pdf, paper.path, out_pdf, merged_evidences
                                )
                                print(f"[Paper {paper.paper_id}] Highlighted: {out_pdf}")
                            except Exception as exc:  # noqa: BLE001
                                print(f"[Paper {paper.paper_id}] Highlight error (non-fatal): {exc!r}")
                        else:
                            print(f"[Paper {paper.paper_id}] WARNING: No evidence strings found — LLM may have returned flat values instead of nested {{value, evidence}} objects")

                    for row in value_rows:
                        await queue.put({**base_row, **row, "Error": ""})
                except Exception as exc:  # noqa: BLE001
                    print(f"[Paper {paper.paper_id}] Exception: {exc!r}")
                    traceback.print_exc()
                    await queue.put(
                        {
                            **base_row,
                            **_blank_llm_values(llm_columns),
                            "Error": repr(exc),
                        }
                    )

        try:
            await asyncio.gather(*(handle(paper) for paper in papers))
        finally:
            await queue.put(None)
            await writer_task

    _csv_to_excel(args.output_csv, args.output_xlsx, template_path)
    print(f"Saved CSV: {args.output_csv}")
    print(f"Saved XLSX: {args.output_xlsx}")


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        asyncio.run(main())
    finally:
        print(f"Elapsed: {time.perf_counter() - start:.2f}s")
