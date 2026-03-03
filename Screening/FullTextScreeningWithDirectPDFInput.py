from __future__ import annotations

"""
Full-text screening script that sends PDFs directly to DMX `/v1/responses`.

This is an alternative to `FullTextScreeningWithPDFInput.py` (PDF -> images -> LLM).
Here we send the PDF as `input_file` with base64 `file_data`.

API endpoint (default):
  https://www.dmxapi.cn/v1/responses

Auth fallback:
  1) Authorization: <API_KEY>
  2) Authorization: Bearer <API_KEY>  (if 401/403 on the first attempt)
"""

import argparse
import asyncio
import base64
import csv
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from TextHighlight import highlight_pdf

import httpx
from dotenv import load_dotenv

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


# Keep prompts local to this script to avoid changing the existing vision pipeline.
SYSTEM_PROMPT = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

IMPORTANT CONTEXT:
- You will receive ONLY PDF page images.
- You MUST base all judgments strictly on visible content in the images.
- Tables and figures are valid evidence.
- Do NOT assume missing information.
- Do NOT infer unstated details.
- If something is not explicitly visible in the PDF images, treat it as Not Matched.

Screening Type:
This is FULL-TEXT screening (not abstract screening).

Component Evaluation Rules:

Population (P):
- Matched ONLY if explicit textual evidence supports the target population.
- If explicitly contradictory → Not Matched.
- If not mentioned at all → Not Matched.

Intervention (I):
- Matched ONLY if iron supplementation therapy is explicitly described.
- Variations in dose/duration acceptable.
- If explicitly contradictory → Not Matched.
- If not mentioned → Not Matched.

Comparison (C):
- Matched ONLY if a comparator group is explicitly described.
- If explicitly contradictory → Not Matched.
- If not mentioned → Not Matched.

Outcome (O):
- Matched ONLY if at least one required outcome is explicitly reported.
- If explicitly contradictory → Not Matched.
- If not mentioned → Not Matched.

Extra Requirements:
- Matched ONLY if study design explicitly satisfies requirements.
- If explicitly contradictory → Not Matched.
- If not mentioned → Not Matched.

Final Inclusion Rule:
- Count matched components among P, I, C, O, Extra.
- If ≥4 components are Matched → Flag = 1.
- If <4 components are Matched → Flag = 0.

CRITICAL Evidence Extraction Rule (UPDATED – STRICT):

For EVERY component (P, I, C, O, Extra):

1. Evidence MUST be extracted regardless of whether Matched is Yes or No.
2. If Matched = Yes:
   - Extract exact original text that directly supports why it satisfies the requirement.
3. If Matched = No:
   - If the text explicitly contradicts the requirement → extract exact contradictory text.
   - If the text explicitly shows a different population/intervention/outcome/design → extract that text.
4. If the component is completely not mentioned anywhere in the PDF images:
   - Evidence MUST be empty string ("").

CRITICAL REQUIREMENT FOR EVIDENCE:

For each evidence item (Population, Intervention, Comparison, Outcome, Extra):

- The evidence MUST be copied verbatim from the PDF.
- The text must match the original wording exactly.
- Do NOT paraphrase.
- Do NOT summarize.
- Do NOT rewrite.
- Do NOT modify grammar.
- Do NOT change tense.
- Do NOT omit words.
- Do NOT add words.
- Do NOT merge sentences.
- Do NOT correct typos.
- Do NOT remove punctuation.

If you cannot find an exact sentence in the PDF, return an empty string for that evidence item.

The evidence must be directly traceable to a visible sentence in the PDF page images.

Global Summary Requirement (NEW):
- Regardless of Flag = 0 or 1,
- You MUST provide a short overall summary in the Conclusion section.
- The summary must briefly explain why the paper is included or excluded based on component counts.
- The summary must be concise but logically complete.

STRICT FORMAT ENFORCEMENT:
- You MUST output ALL five components.
- You MUST NOT omit any section.
- You MUST NOT provide explanations outside the template.
- Output ONLY in the required template.
- If format is violated, regenerate internally before answering.
"""


USER_PROMPT_TEMPLATE = """
PICO: 
        Population (P): 铁缺乏但尚未贫血的儿童(0-6岁), 合并疾病?
        Intervention (I): 铁剂治疗(每日2 mg/kg元素铁的口服铁剂治疗,疗程为12周),剂量,疗程
        Comparison (C): 不进行铁剂治疗
        Outcome (O): Critical:血色素水平, 贫血的发生率, 生长发育指标; 
                    Important: 安全性指标：胃肠道反应、食欲下降, 神经认知发育, 肠道菌群, 感染性疾病患病率
        Extra requirements: Study design: SR、RCT、观察性研究

Input Format:
You will receive PDF page images labeled:
"Paper ID <ID> - PDF Page <page_number>:"

Use ONLY the images to judge.

Task:
1. Evaluate each paper independently.
2. Evaluate P, I, C, O, Extra separately.
3. No inference beyond visible text.
4. Apply ≥4 component rule.
5. Extract exact evidence for ALL components (including Not Matched).

STRICT OUTPUT TEMPLATE (NO EXTRA TEXT):

ID: <Paper ID>
Flag: 0 or 1

Reason:

Population:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Intervention:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Comparison:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Outcome:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Extra:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Conclusion:
"<concise overall explanation why the paper is included (Flag=1) or excluded (Flag=0), based strictly on visible matched component count>"
"""

def extract_evidence(text):
    components = ["Population", "Intervention", "Comparison", "Outcome", "Extra"]
    evidences = {}

    for comp in components:
        pattern = rf"{comp}:\s*Matched:\s*(?:Yes|No)\s*Evidence:\s*\"(.*?)\""
        match = re.search(pattern, text, re.DOTALL)

        if match:
            evidences[comp] = match.group(1).strip()
        else:
            evidences[comp] = ""

    return evidences

def extract_conclusion(text: str) -> str:
    pattern = r'Conclusion:\s*"(.*?)"'
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""

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

    # Slice pages by building a new in-memory PDF to reduce size/cost.
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
    # OpenAI Responses-style output: list with message blocks containing output_text content.
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

    # Gateway fallbacks (non-standard but seen in some wrappers).
    for key in ("output_text", "text"):
        v = resp_json.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


_FLAG_RE = re.compile(r"(?mi)^\s*Flag\s*:\s*([01])\s*$")


def _extract_flag(text: str) -> str:
    m = _FLAG_RE.search(text or "")
    return m.group(1) if m else ""


async def _post_with_auth_fallback(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    # Try 1: Authorization: <key> (per DMX sample)
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403):
        return r1

    # Try 2: Authorization: Bearer <key>
    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    r2 = await client.post(url, headers=headers2, json=payload, timeout=timeout_s)
    return r2


async def _call_with_retry(coro_func, *args, retries: int, delay_s: float):
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as e:  # noqa: BLE001
            last_exc = e
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
    for i, p in enumerate(pdfs, start=1):
        out.append(Paper(paper_id=i, path=p.resolve(), title=p.stem))
    return out


def _safe_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except Exception:
        return str(path)


async def _csv_writer(queue: "asyncio.Queue[dict[str, Any] | None]", output_csv: Path) -> None:
    """
    Single-writer task for streaming results to CSV.

    Keeping one writer avoids file corruption when multiple async tasks complete concurrently.
    """
    fieldnames = ["ID", "Title", "RelativePath", "Flag", "Reason"]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        f.flush()  # Make the header visible immediately.

        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                writer.writerow(item)
                f.flush()  # Ensure the row is visible immediately in editors.
            finally:
                queue.task_done()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Full-text screening via DMX Responses API with direct PDF input")
    parser.add_argument("--resources-dir", type=Path, default=PROJECT_DIR / "resources")
    parser.add_argument("--output-csv", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_screening_results_pdf_direct.csv")

    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1")
    parser.add_argument("--model", type=str, default="gpt-5-mini")

    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1")
    parser.add_argument("--pdf-pages", type=str, default="all", help="e.g. all or 1-3,5 (requires pymupdf)")

    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--max-concurrency", type=int, default=5)

    args = parser.parse_args()

    load_dotenv(SCRIPT_DIR / ".env", override=True)
    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing env var in Screening/.env: {args.api_key_env}")

    endpoint = args.base_url.rstrip("/") + "/responses"

    resources_dir = args.resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources-dir not found: {resources_dir}")

    papers = _discover_pdfs(resources_dir)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)

    pages = _parse_pages_spec(str(args.pdf_pages))
    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async with httpx.AsyncClient() as client:
        writer_task = asyncio.create_task(_csv_writer(queue, args.output_csv))

        async def handle(p: Paper) -> None:
            async with sem:
                prompt = SYSTEM_PROMPT + "\n\n" + USER_PROMPT_TEMPLATE.format(paper_id=p.paper_id)
                try:
                    pdf_bytes = _load_pdf_bytes(p.path, pages)
                    b64 = base64.b64encode(pdf_bytes).decode("ascii")

                    payload = {
                        "model": args.model,
                        "input": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "input_file",
                                        "filename": p.path.name,
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
                        # Keep CSV minimal (no Error column). Print errors to console for debugging.
                        print(f"[Paper {p.paper_id}] HTTP {resp.status_code}: {resp.text[:200]}")
                        await queue.put(
                            {
                                "ID": p.paper_id,
                                "Title": p.title,
                                "RelativePath": _safe_relative(p.path, PROJECT_DIR),
                                "Flag": "0",
                                "Reason": "",
                            }
                        )
                        return

                    data = resp.json()
                    text = _extract_output_text(data)
                    flag = _extract_flag(text)
                    evidences = extract_evidence(text)
                    conclusion = extract_conclusion(text)

                    # ====== 高亮PDF ======
                    try:
                        input_pdf = Path(p.path)

                        output_dir = Path("../outputs")
                        output_dir.mkdir(exist_ok=True)

                        output_pdf = output_dir / input_pdf.name

                        highlight_pdf(
                            input_pdf=input_pdf,
                            output_pdf=output_pdf,
                            evidences=evidences
                        )


                    except Exception as e:
                        print(f"[Paper {p.paper_id}] Highlight error: {e!r}")

                    await queue.put(
                        {
                            "ID": p.paper_id,
                            "Title": p.title,
                            "RelativePath": _safe_relative(p.path, PROJECT_DIR),
                            "Flag": flag,
                            "Reason": evidences,
                        }
                    )

                except Exception as e:  # noqa: BLE001
                    print(f"[Paper {p.paper_id}] Exception: {e!r}")
                    await queue.put(
                        {
                            "ID": p.paper_id,
                            "Title": p.title,
                            "RelativePath": _safe_relative(p.path, PROJECT_DIR),
                            "Flag": "0",
                            "Reason": "",
                        }
                    )

        try:
            await asyncio.gather(*(handle(p) for p in papers))
        finally:
            # Stop writer and ensure everything is flushed/closed.
            await queue.put(None)
            await writer_task

    print(f"Saved: {args.output_csv}")


if __name__ == "__main__":
    start = time.perf_counter()
    try:
        asyncio.run(main())
    finally:
        print(f"Elapsed: {time.perf_counter() - start:.2f}s")
