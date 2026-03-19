import asyncio
import base64
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

import httpx
from dotenv import load_dotenv

from TextHighlight import highlight_pdf

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)


PICOS_SYSTEM_PROMPT = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Core Directives:
- You will receive ONLY PDF pages.
- You MUST base all judgments strictly on visible content in the PDF. Tables and figures are valid evidence.
- Do NOT assume missing information or infer unstated details.
- If something is not explicitly visible, treat it as Not Matched.
- This is FULL-TEXT screening (not abstract screening).

Evaluation Scope:
- Always evaluate the following SPIC components:
  Study Design (S), Population (P), Intervention (I), Comparison (C).

- Outcome (O) should ONLY be evaluated if the user explicitly provides an Outcome requirement.
  If Outcome is not provided, completely ignore Outcome in both evaluation and counting.

- Extra Requirements (if any) should also be evaluated.

Component Evaluation Rules:

1. Study Design (S)
Matched ONLY if the study design (e.g., randomized controlled trial, cohort study, case-control study) is explicitly described.

2. Population (P)
Matched ONLY if explicit textual evidence supports the target population.

3. Intervention (I)
Matched ONLY if the specific intervention therapy is explicitly described.

4. Comparison (C)
Matched ONLY if a comparator group is explicitly described.

5. Outcome (O) – ONLY evaluate if provided
Matched ONLY if the study explicitly reports outcomes corresponding to the user-specified outcome concept.

6. Extra Requirements
Matched ONLY if the text explicitly satisfies the extra requirement.

Final Inclusion Rule:
- Count matched components among:
  S, P, I, C
  Outcome (only if provided)
  Extra requirements (if provided)

- If ≥4 components are Matched → Flag = 1
- If <4 components are Matched → Flag = 0


CRITICAL Evidence Extraction Rule (STRICT):

For EVERY evaluated component (S, P, I, C, and optionally O, Extra), evidence MUST be extracted regardless of whether Matched is Yes or No.

Evidence rules:

If Matched = Yes:
Extract the exact original text that directly supports why it satisfies the requirement.

If Matched = No:
Extract the exact contradictory text, or text indicating a different population/intervention/comparison/study design/etc.

If the information is completely not mentioned:
The Evidence MUST be an empty string ("").

If multiple candidate sentences exist:
Select the single most direct supporting sentence only.


Evidence constraints (STRICT):

Evidence must be copied verbatim from the PDF.

Do NOT:
- paraphrase
- summarize
- rewrite
- correct grammar
- modify tense
- omit words
- add words
- merge sentences
- remove punctuation

The extracted evidence must be directly traceable to a visible sentence in the PDF.

Only ONE piece of evidence is allowed per component.

The evidence must be a single continuous span of text from one location in the document.

Do NOT combine multiple sentences from different locations.


STRICT OUTPUT TEMPLATE:

DOI : the doi of this paper
Flag: <0 or 1>

Reason:

Study Design:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Population:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Intervention:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Comparison:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Outcome: (ONLY if Outcome requirement is provided)
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Extra:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Conclusion:
"<concise explanation why the paper is included or excluded based strictly on matched component count>"
"""

PECO_SYSTEM_PROMPT = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Core Directives:
- You will receive ONLY PDF pages.
- You MUST base all judgments strictly on visible content in the PDF. Tables and figures are valid evidence.
- Do NOT assume missing information or infer unstated details.
- If something is not explicitly visible, treat it as Not Matched.
- This is FULL-TEXT screening (not abstract screening).

Evaluation Scope:
Always evaluate the following PECO components:

Population (P)
Exposure (E)
Comparison (C)
Outcome (O)

Component Evaluation Rules:

1. Population (P)
Matched ONLY if explicit textual evidence supports the target population described in the PECO query.

2. Exposure (E)
Matched ONLY if the exposure factor (risk factor, environmental factor, behavior, condition, etc.) is explicitly described.

3. Comparison (C)
Matched ONLY if a comparison group or reference group is explicitly described.

4. Outcome (O)
Matched ONLY if the study explicitly reports outcomes corresponding to the user-specified outcome concept.

Final Inclusion Rule:
- Count matched components among:
  P, E, C, O

- If ≥3 components are Matched → Flag = 1
- If <3 components are Matched → Flag = 0


CRITICAL Evidence Extraction Rule (STRICT):

For EVERY evaluated component (P, E, C, O), evidence MUST be extracted regardless of whether Matched is Yes or No.

Evidence rules:

If Matched = Yes:
Extract the exact original text that directly supports why it satisfies the requirement.

If Matched = No:
Extract the exact contradictory text, or text indicating a different population/exposure/comparison/outcome.

If the information is completely not mentioned:
The Evidence MUST be an empty string ("").

If multiple candidate sentences exist:
Select the single most direct supporting sentence only.


Evidence constraints (STRICT):

Evidence must be copied verbatim from the PDF.

Do NOT:
- paraphrase
- summarize
- rewrite
- correct grammar
- modify tense
- omit words
- add words
- merge sentences
- remove punctuation

The extracted evidence must be directly traceable to a visible sentence in the PDF.

Only ONE piece of evidence is allowed per component.

The evidence must be a single continuous span of text from one location in the document.

Do NOT combine multiple sentences from different locations.


STRICT OUTPUT TEMPLATE:

DOI : the doi of this paper
Flag: <0 or 1>

Reason:

Population:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Exposure:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Comparison:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Outcome:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Conclusion:
"<concise explanation why the paper is included or excluded based strictly on matched component count>"
"""

PIRO_SYSTEM_PROMPT = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Core Directives:
- You will receive ONLY PDF pages.
- You MUST base all judgments strictly on visible content in the PDF. Tables and figures are valid evidence.
- Do NOT assume missing information or infer unstated details.
- If something is not explicitly visible, treat it as Not Matched.
- This is FULL-TEXT screening (not abstract screening).

Evaluation Scope:
Always evaluate the following PIRO components:

Population (P)
Indicator (I)
Reference (R)
Outcome (O)

Component Evaluation Rules:

1. Population (P)
Matched ONLY if explicit textual evidence supports the target population described in the PIRO query.

2. Indicator (I)
Matched ONLY if the indicator (e.g., biomarker, diagnostic test, prognostic factor, exposure measurement, clinical score, or measurement variable) is explicitly described.

3. Reference (R)
Matched ONLY if a reference or comparator is explicitly described.
This may include:
- a control group
- a baseline level
- a standard diagnostic method
- a reference measurement
- a comparison group

4. Outcome (O)
Matched ONLY if the study explicitly reports outcomes corresponding to the user-specified outcome concept.

Final Inclusion Rule:
- Count matched components among:
  P, I, R, O

- If ≥3 components are Matched → Flag = 1
- If <3 components are Matched → Flag = 0


CRITICAL Evidence Extraction Rule (STRICT):

For EVERY evaluated component (P, I, R, O), evidence MUST be extracted regardless of whether Matched is Yes or No.

Evidence rules:

If Matched = Yes:
Extract the exact original text that directly supports why it satisfies the requirement.

If Matched = No:
Extract the exact contradictory text, or text indicating a different population/indicator/reference/outcome.

If the information is completely not mentioned:
The Evidence MUST be an empty string ("").

If multiple candidate sentences exist:
Select the single most direct supporting sentence only.


Evidence constraints (STRICT):

Evidence must be copied verbatim from the PDF.

Do NOT:
- paraphrase
- summarize
- rewrite
- correct grammar
- modify tense
- omit words
- add words
- merge sentences
- remove punctuation

The extracted evidence must be directly traceable to a visible sentence in the PDF.

Only ONE piece of evidence is allowed per component.

The evidence must be a single continuous span of text from one location in the document.

Do NOT combine multiple sentences from different locations.


STRICT OUTPUT TEMPLATE:

DOI : the doi of this paper
Flag: <0 or 1>

Reason:

Population:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Indicator:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Reference:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Outcome:
Matched: <Yes/No>
Evidence: <exact copied text or empty string>

Conclusion:
"<concise explanation why the paper is included or excluded based strictly on matched component count>"
"""


@dataclass(frozen=True)
class FullTextPaper:
    paper_id: int
    title: str
    pdf_path: Path


@dataclass(frozen=True)
class FullTextRequest:
    paper: FullTextPaper
    pico_dict: dict[str, str]
    project_type: str


@dataclass(frozen=True)
class WebFullTextConfig:
    base_url: str = "https://www.dmxapi.cn/v1"
    model: str = "gpt-4.1"
    api_key_env: str = "DMX_API_KEY_1"
    timeout: float = 300.0
    retries: int = 3
    retry_delay: float = 3.0
    max_concurrency: int = 5
    pdf_pages: str = "all"


@dataclass(frozen=True)
class WebFullTextRuntime:
    endpoint: str
    api_key: str
    model: str
    timeout: float
    retries: int
    retry_delay: float
    max_concurrency: int
    pdf_pages: str
    selected_pages: Optional[list[int]]


def clean_evidence(text: str) -> str:
    if not text:
        return ""
    return text.strip().strip('"').strip("'")


def extract_evidence(text):
    components = ["Study Design", "Population", "Intervention", "Comparison", "Outcome", "Indicator", "Reference", "Exposure", "Extra"]
    evidences = {}

    for comp in components:
        pattern = rf"{comp}:\s*Matched:\s*(?:Yes|No)\s*Evidence:\s*(.*?)(?=\n[A-Z][a-z]+:|\Z)"
        match = re.search(pattern, text, re.DOTALL)

        if match:
            evidences[comp] = clean_evidence(match.group(1))
        else:
            evidences[comp] = ""

    return evidences


def extract_conclusion(text: str) -> str:
    match = re.search(r'Conclusion:\s*\"?(.*?)\"?(?=\n[A-Z][a-z]+:|\Z)', text, re.DOTALL)
    return match.group(1).strip() if match else "No conclusion provided."


def _normalize_project_type(project_type: str) -> str:
    normalized = (project_type or "PICOS").upper()
    return "PICOS" if normalized in {"PICO", "SPICO"} else normalized


def _normalize_pico_dict(pico_dict: Optional[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(key): "" if value is None else str(value)
        for key, value in (pico_dict or {}).items()
    }


def _coerce_paper(paper: Any) -> FullTextPaper:
    if isinstance(paper, FullTextPaper):
        return paper
    if not isinstance(paper, Mapping):
        raise TypeError(f"Unsupported paper input: {type(paper)!r}")

    paper_id = int(paper["id"])
    pdf_path = Path(str(paper["pdf_path"]))
    title = str(paper.get("title") or pdf_path.stem)
    return FullTextPaper(paper_id=paper_id, title=title, pdf_path=pdf_path)


def _parse_pages_spec(spec: str) -> Optional[list[int]]:
    s = (spec or "").strip().lower()
    if s in {"", "all", "*"}:
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


def _load_pdf_bytes(pdf_path: Path, pages: Optional[list[int]]) -> bytes:
    data = pdf_path.read_bytes()
    if pages is None:
        return data

    if fitz is None:
        raise RuntimeError("PyMuPDF is required for pdf_pages/page slicing. Install `pymupdf`.")

    with fitz.open(stream=data, filetype="pdf") as src:
        page_count = src.page_count
        selected = [p for p in pages if 1 <= p <= page_count]
        if not selected:
            return data

        with fitz.open() as out:
            for p in selected:
                out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
            return out.write()


def _read_env_config() -> WebFullTextConfig:
    return WebFullTextConfig(
        base_url=os.getenv("WEB_FULLTEXT_BASE_URL", "https://www.dmxapi.cn/v1"),
        model=os.getenv("WEB_FULLTEXT_MODEL", "gpt-4.1"),
        api_key_env=os.getenv("WEB_FULLTEXT_API_KEY_ENV", "DMX_API_KEY_1"),
        timeout=float(os.getenv("WEB_FULLTEXT_TIMEOUT", "300.0")),
        retries=int(os.getenv("WEB_FULLTEXT_RETRIES", "3")),
        retry_delay=float(os.getenv("WEB_FULLTEXT_RETRY_DELAY", "3.0")),
        max_concurrency=int(os.getenv("WEB_FULLTEXT_MAX_CONCURRENCY", "5")),
        pdf_pages=os.getenv("WEB_FULLTEXT_PDF_PAGES", "all"),
    )


def _resolve_runtime_config(config: WebFullTextConfig | Mapping[str, Any] | None) -> WebFullTextRuntime:
    default_cfg = _read_env_config()
    endpoint_override: Optional[str] = None

    if config is None:
        merged = asdict(default_cfg)
    elif isinstance(config, WebFullTextConfig):
        merged = asdict(config)
    elif isinstance(config, Mapping):
        merged = {**asdict(default_cfg), **dict(config)}
        endpoint_value = merged.pop("endpoint", None)
        if endpoint_value:
            endpoint_override = str(endpoint_value)
    else:
        raise TypeError(f"Unsupported config input: {type(config)!r}")

    resolved = WebFullTextConfig(**merged)
    api_key = os.getenv(resolved.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing env var in Screening/.env: {resolved.api_key_env}")

    endpoint = endpoint_override or resolved.base_url.rstrip("/") + "/responses"
    pdf_pages = str(resolved.pdf_pages or "all")
    return WebFullTextRuntime(
        endpoint=endpoint,
        api_key=api_key,
        model=resolved.model,
        timeout=max(1.0, float(resolved.timeout)),
        retries=max(1, int(resolved.retries)),
        retry_delay=max(0.0, float(resolved.retry_delay)),
        max_concurrency=max(1, int(resolved.max_concurrency)),
        pdf_pages=pdf_pages,
        selected_pages=_parse_pages_spec(pdf_pages),
    )


def _get_system_prompt(project_type: str) -> str:
    normalized = _normalize_project_type(project_type)
    if normalized == "PECO":
        return PECO_SYSTEM_PROMPT
    if normalized == "PIRO":
        return PIRO_SYSTEM_PROMPT
    return PICOS_SYSTEM_PROMPT


def _build_user_prompt(request: FullTextRequest) -> str:
    paper = request.paper
    pico_dict = request.pico_dict
    project_type = _normalize_project_type(request.project_type)

    if project_type == "PECO":
        return f"""
        Target PECO Criteria for this Evaluation:
        - Population (P): {pico_dict.get('p', '')}
        - Exposure (E): {pico_dict.get('e', '')}
        - Comparison (C): {pico_dict.get('c', '')}
        - Outcome (O): {pico_dict.get('o', '')}
        - Additional Criteria: {pico_dict.get('es', '')}

        Instructions for this task:
        Evaluate the paper below against the Target PECO Criteria using the strict rules and output template defined in your system instructions. Evaluate P, E, C, O, and Extra separately.

        Input Data:
        [Paper ID: {paper.paper_id}]
        [Paper Title: {paper.title}]
        [PDF Page Images Provided Below]
        """

    if project_type == "PIRO":
        return f"""
        Target PIRO Criteria for this Evaluation:
        - Population (P): {pico_dict.get('p', '')}
        - Indicator (I): {pico_dict.get('i', '')}
        - Reference (R): {pico_dict.get('r', '')}
        - Outcome (O): {pico_dict.get('o', '')}
        - Additional Criteria: {pico_dict.get('es', '')}

        Instructions for this task:
        Evaluate the paper below against the Target PIRO Criteria using the strict rules and output template defined in your system instructions. Evaluate P, I, R, O, and Extra separately.

        Input Data:
        [Paper ID: {paper.paper_id}]
        [Paper Title: {paper.title}]
        [PDF Page Images Provided Below]
        """

    return f"""
            Target PICS Criteria for this Evaluation:
            - Study Design (S): {pico_dict.get('s', '')}
            - Population (P): {pico_dict.get('p', '')}
            - Intervention (I): {pico_dict.get('i', '')}
            - Comparison (C): {pico_dict.get('c', '')}
            - Outcome (O): {pico_dict.get('o', '')}
            - Additional Criteria: {pico_dict.get('es', '')}

            Instructions for this task:
            Evaluate the paper below against the Target PICS Criteria using the strict rules and output template defined in your system instructions. Evaluate P, I, C, O, and Extra separately.

            Input Data:
            [Paper ID: {paper.paper_id}]
            [Paper Title: {paper.title}]
            [PDF Page Images Provided Below]
            """


def _build_payload(model_name: str, pdf_bytes: bytes, filename: str, prompt: str) -> dict[str, Any]:
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return {
        "model": model_name,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "filename": filename, "file_data": f"data:application/pdf;base64,{b64}"},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    }


def _error_result(paper_id: int) -> dict[str, Any]:
    return {"id": paper_id, "decision": "Error", "evidence": "{}", "hl_path": None}


def _extract_flag(text: str) -> str:
    m = re.search(r"(?mi)^\s*Flag\s*:\s*([01])\s*$", text or "")
    return m.group(1) if m else "0"


def _extract_output_text(resp_json: dict[str, Any]) -> str:
    out_parts = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    out_parts.append(text)
    if out_parts:
        return "\n".join(out_parts)
    return resp_json.get("output_text", resp_json.get("text", ""))


async def _call_with_retry(coro_func, *args, retries=3, delay_s=3.0):
    last_exc = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as e:
            last_exc = e
            await asyncio.sleep(delay_s)
    raise last_exc


async def _post_with_auth_fallback(client, url, api_key, payload, timeout_s):
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403):
        return r1
    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)


async def process_single_paper(client: httpx.AsyncClient, runtime: WebFullTextRuntime, request: FullTextRequest) -> dict[str, Any]:
    paper = request.paper
    pdf_path = paper.pdf_path
    if not pdf_path.exists():
        return _error_result(paper.paper_id)

    try:
        prompt = _get_system_prompt(request.project_type) + "\n\n" + _build_user_prompt(request)
        pdf_bytes = _load_pdf_bytes(pdf_path, runtime.selected_pages)
        payload = _build_payload(runtime.model, pdf_bytes, pdf_path.name, prompt)
    except Exception:
        return _error_result(paper.paper_id)

    try:
        resp = await _call_with_retry(
            _post_with_auth_fallback,
            client,
            runtime.endpoint,
            runtime.api_key,
            payload,
            runtime.timeout,
            retries=runtime.retries,
            delay_s=runtime.retry_delay,
        )
        if resp.status_code != 200:
            return _error_result(paper.paper_id)

        text = _extract_output_text(resp.json())
        flag = _extract_flag(text)
        evidences = extract_evidence(text)
        conclusion = extract_conclusion(text)
        decision = "Included" if flag == "1" else "Excluded"

        hl_path_str = None
        try:
            hl_dir = pdf_path.parent / "highlighted"
            hl_dir.mkdir(exist_ok=True)
            out_pdf = hl_dir / f"HL_{pdf_path.name}"
            highlight_pdf(pdf_path, out_pdf, evidences)
            hl_path_str = str(out_pdf)
        except Exception as e:
            print(f"Highlight error for ID {paper.paper_id}: {e}")

        evidence_json = json.dumps({"evidences": evidences, "conclusion": conclusion}, ensure_ascii=False)
        return {"id": paper.paper_id, "decision": decision, "evidence": evidence_json, "hl_path": hl_path_str}
    except Exception:
        return _error_result(paper.paper_id)


async def _run_web_fulltext(
    papers,
    pico_dict,
    project_type,
    config: WebFullTextConfig | Mapping[str, Any] | None = None,
):
    runtime = _resolve_runtime_config(config)
    normalized_project_type = _normalize_project_type(project_type)
    normalized_pico = _normalize_pico_dict(pico_dict)
    requests = [
        FullTextRequest(
            paper=_coerce_paper(paper),
            pico_dict=normalized_pico,
            project_type=normalized_project_type,
        )
        for paper in papers
    ]

    sem = asyncio.Semaphore(runtime.max_concurrency)
    async with httpx.AsyncClient(timeout=runtime.timeout) as client:
        async def _bounded_process(request: FullTextRequest):
            async with sem:
                return await process_single_paper(client, runtime, request)

        tasks = [_bounded_process(request) for request in requests]
        return await asyncio.gather(*tasks)


def run_fulltext_ai_sync(
    papers,
    pico_dict,
    project_type="PICOS",
    config: WebFullTextConfig | Mapping[str, Any] | None = None,
):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run_web_fulltext(papers, pico_dict, project_type, config=config))
    finally:
        loop.close()
