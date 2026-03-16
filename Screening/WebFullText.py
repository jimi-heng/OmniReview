import asyncio
import base64
import os
import re
import json
from pathlib import Path
from typing import Any
import httpx
from dotenv import load_dotenv

# 引入你们的高亮绘图工具
from TextHighlight import highlight_pdf

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

# 保留你们极其严格的系统提示词
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

import re

def clean_evidence(text: str) -> str:
    if not text:
        return ""
    return text.strip().strip('"').strip("'")

def extract_evidence(text):
    components = ["Study Design", "Population", "Intervention", "Comparison", "Outcome", "Indicator",  "Reference", "Exposure", "Extra"]
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

def _extract_flag(text: str) -> str:
    m = re.search(r"(?mi)^\s*Flag\s*:\s*([01])\s*$", text or "")
    return m.group(1) if m else "0"

def _extract_output_text(resp_json: dict[str, Any]) -> str:
    out_parts = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message": continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip(): out_parts.append(text)
    if out_parts: return "\n".join(out_parts)
    return resp_json.get("output_text", resp_json.get("text", ""))

async def _call_with_retry(coro_func, *args, retries=3, delay_s=3.0):
    last_exc = None
    for _ in range(retries):
        try: return await coro_func(*args)
        except Exception as e:
            last_exc = e
            await asyncio.sleep(delay_s)
    raise last_exc

async def _post_with_auth_fallback(client, url, api_key, payload, timeout_s):
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403): return r1
    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)

async def process_single_paper(client, endpoint, api_key, model_name, paper, pico_dict, project_type):
    if project_type == 'PECO':
        user_prompt = f"""
        Target PECO Criteria for this Evaluation:
        - Population (P): {pico_dict.get('p', '')}
        - Exposure (E): {pico_dict.get('e', '')}
        - Comparison (C): {pico_dict.get('c', '')}
        - Outcome (O): {pico_dict.get('o', '')}
        - Extra requirements: None

        Instructions for this task:
        Evaluate the paper below against the Target PECO Criteria using the strict rules and output template defined in your system instructions. Evaluate P, E, C, O, and Extra separately.

        Input Data:
        [Paper ID: {paper['id']}]
        [Paper Title: {paper['title']}]
        [PDF Page Images Provided Below]
        """

        prompt = PECO_SYSTEM_PROMPT + "\n\n" + user_prompt
    elif project_type == 'PIRO':
        user_prompt = f"""
        Target PIRO Criteria for this Evaluation:
        - Population (P): {pico_dict.get('p', '')}
        - Indicator (I): {pico_dict.get('i', '')}
        - Reference (R): {pico_dict.get('r', '')}
        - Outcome (O): {pico_dict.get('o', '')}
        - Extra requirements: None

        Instructions for this task:
        Evaluate the paper below against the Target PIRO Criteria using the strict rules and output template defined in your system instructions. Evaluate P, I, R, O, and Extra separately.

        Input Data:
        [Paper ID: {paper['id']}]
        [Paper Title: {paper['title']}]
        [PDF Page Images Provided Below]
        """

        prompt = PIRO_SYSTEM_PROMPT + "\n\n" + user_prompt
    else :
        # 1. 动态拼装用户在前端设置的PICOS
        user_prompt = f"""
                Target PICS Criteria for this Evaluation:
                - Study Design (S): {pico_dict.get('s', '')}
                - Population (P): {pico_dict.get('p', '')}
                - Intervention (I): {pico_dict.get('i', '')}
                - Comparison (C): {pico_dict.get('c', '')}
                -Outcome (O): {pico_dict.get('o', '')}
                - Extra requirements: None

                Instructions for this task:
                Evaluate the paper below against the Target PICS Criteria using the strict rules and output template defined in your system instructions. Evaluate P, I, C, O, and Extra separately.

                Input Data:
                [Paper ID: {paper['id']}]
                [Paper Title: {paper['title']}]
                [PDF Page Images Provided Below]
                """
        prompt = PICOS_SYSTEM_PROMPT + "\n\n" + user_prompt


    # 2. 读取之前下载好的 PDF
    pdf_path = Path(paper['pdf_path'])
    if not pdf_path.exists():
        return {'id': paper['id'], 'decision': 'Error', 'evidence': '{}', 'hl_path': None}

    try:
        pdf_bytes = pdf_path.read_bytes()
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
    except Exception as e:
        return {'id': paper['id'], 'decision': 'Error', 'evidence': '{}', 'hl_path': None}

    payload = {
        "model": model_name,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "filename": pdf_path.name, "file_data": f"data:application/pdf;base64,{b64}"},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    }

    # 3. 发送给大模型进行多模态阅片
    try:
        resp = await _call_with_retry(_post_with_auth_fallback, client, endpoint, api_key, payload, 300.0)
        if resp.status_code != 200:
            return {'id': paper['id'], 'decision': 'Error', 'evidence': '{}', 'hl_path': None}

        text = _extract_output_text(resp.json())
        flag = _extract_flag(text)
        evidences = extract_evidence(text)
        conclusion = extract_conclusion(text)
        decision = 'Included' if flag == '1' else 'Excluded'

        print(evidences)
        print("\n")

        # 4. 调用 TextHighlight 进行 PDF 原文高亮标注！
        hl_path_str = None
        try:
            hl_dir = pdf_path.parent / "highlighted"
            hl_dir.mkdir(exist_ok=True)
            out_pdf = hl_dir / f"HL_{pdf_path.name}"
            highlight_pdf(pdf_path, out_pdf, evidences)
            hl_path_str = str(out_pdf)
        except Exception as e:
            print(f"Highlight error for ID {paper['id']}: {e}")

        # 将证据打包成 JSON 存入数据库
        evidence_json = json.dumps({'evidences': evidences, 'conclusion': conclusion}, ensure_ascii=False)
        return {'id': paper['id'], 'decision': decision, 'evidence': evidence_json, 'hl_path': hl_path_str}

    except Exception as e:
        return {'id': paper['id'], 'decision': 'Error', 'evidence': '{}', 'hl_path': None}

async def _run_web_fulltext(papers, pico_dict, project_type):
    api_key = os.getenv("DMX_API_KEY_1")
    model_name = "gpt-4.1"
    endpoint = "https://www.dmxapi.cn/v1/responses"

    sem = asyncio.Semaphore(5) # 并发量控制
    async with httpx.AsyncClient(timeout=300.0) as client:
        async def _bounded_process(p):
            async with sem:
                return await process_single_paper(client, endpoint, api_key, model_name, p, pico_dict, project_type)

        tasks = [_bounded_process(p) for p in papers]
        return await asyncio.gather(*tasks)

def run_fulltext_ai_sync(papers, pico_dict, project_type='PICOS'):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run_web_fulltext(papers, pico_dict, project_type))
    finally:
        loop.close()