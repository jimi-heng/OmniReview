import asyncio
import base64
import os
import re
import json
from pathlib import Path
from typing import Any
import httpx
import openpyxl
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

TEMPLATE_PATH = SCRIPT_DIR.parent / "resources" / "Templete for data extraction.xlsx"
OUTPUT_DIR = SCRIPT_DIR.parent / "outputs"

# ===========================================================================
# Excel 模板列定义 (与 "baseline characteristics" 表头一一对应)
# ===========================================================================
# 38 列 A-AL，分为：
#   A-Q  : 研究级字段（每篇论文一组值）
#   R-U  : 干预臂信息（研究级）
#   V-AI : 结局级字段（每个 outcome 一行，研究级字段重复）
#   AJ-AL: 元数据

# 需要 LLM 从 PDF 中提取的研究级字段
STUDY_FIELDS = [
    "Study_ID",                  # E  — FirstAuthor_Year 格式
    "Trial_Number",              # G
    "Study_Name",                # H
    "Country",                   # I
    "Number_of_centers",         # J
    "Study_Inclusion",           # K
    "Exclusion_Criteria",        # L
    "Diagnosis",                 # M
    "Sample_Size",               # N
    "Age",                       # O
    "Gender",                    # P
    "Follow_up",                 # Q  — 数字+单位，例如 6m, 2y
    "Arm_1_Specific_Regimens",   # R
    "Arm1_Drugs",                # S
    "Arm2_Specific_Regimens",    # T
    "Arm2_Drugs",                # U
]

# 结局级字段 — 每个 outcome 一组
OUTCOME_FIELDS = [
    "Outcome_Reported",          # V  — Y or N
    "Name_of_Outcome",           # W
    "Definition",                # X
    "Measurement_Time",          # Y  — 数字+单位，例如 12w, 6m
    # 连续型结局数据 (Mean / SD / N)
    "Arm1_Mean",                 # Z
    "Arm1_SD",                   # AA
    "Arm1_Total_Continuous",     # AB — 连续型的 Arm1 总人数
    "Arm2_Mean",                 # AC
    "Arm2_SD",                   # AD
    "Arm2_Total_Continuous",     # AE — 连续型的 Arm2 总人数
    # 二分类结局数据 (Events / N)
    "Arm1_Events",               # AF
    "Arm1_Total_Dichotomous",    # AG — 二分类的 Arm1 总人数
    "Arm2_Events",               # AH
    "Arm2_Total_Dichotomous",    # AI — 二分类的 Arm2 总人数
    "Note",                      # AJ
]


# ===========================================================================
# 读取 Excel 模板
# ===========================================================================

def load_template_info(template_path: Path | str) -> tuple[list[str], list[str]]:
    """读取模板表头和 intervention 列表"""
    wb = openpyxl.load_workbook(template_path)

    ws = wb["baseline characteristics"]
    headers = []
    for col in range(1, ws.max_column + 1):
        headers.append(ws.cell(row=1, column=col).value or "")

    interventions = []
    if "intervention" in wb.sheetnames:
        ws_int = wb["intervention"]
        for row in range(1, ws_int.max_row + 1):
            v = ws_int.cell(row=row, column=1).value
            if v:
                interventions.append(v)

    wb.close()
    return headers, interventions


# ===========================================================================
# System Prompt — 根据模板列动态构建
# ===========================================================================

def build_system_prompt(interventions: list[str]) -> str:
    intervention_list = "\n".join(f"  - {v}" for v in interventions) if interventions else "  (not specified)"

    return f"""Role:
You are an expert in biomedical data extraction for systematic reviews.

Core Directives:
- You will receive ONLY PDF page images of a research paper.
- You MUST extract data strictly from visible content in the images. Tables, figures, and text are all valid sources.
- Do NOT assume or infer missing data. If a field cannot be found in the paper, use "NR" (Not Reported).
- Evidence text must be copied verbatim — do NOT paraphrase, summarize, or rewrite.

Formatting Rules:
- Study_ID format: FirstAuthor_Year (e.g., Smith_2020). If multiple studies share the same ID, append lowercase letters a, b, c.
- Time durations: number directly followed by unit abbreviation — d (day), w (week), m (month), y (year). Example: 6m, 12w, 2y.
- Use underscore (_) instead of spaces in Arm/Drug regimen fields.
- Numbers and symbols should have a space between them (e.g., p < 0.05).

Known Intervention Categories for this Review:
{intervention_list}
Classify Arm1 and Arm2 drugs into the categories above when possible.

=== STUDY-LEVEL FIELDS (extract ONE set per paper) ===
{chr(10).join(f"- {f}" for f in STUDY_FIELDS)}

=== OUTCOME-LEVEL FIELDS (extract ONE set per outcome; a paper may report MULTIPLE outcomes) ===
For each outcome, determine if it is a continuous outcome (report Mean, SD, Total) or a dichotomous outcome (report Events, Total).
- For continuous outcomes: fill Arm1_Mean, Arm1_SD, Arm1_Total_Continuous, Arm2_Mean, Arm2_SD, Arm2_Total_Continuous. Leave dichotomous fields as "NR".
- For dichotomous outcomes: fill Arm1_Events, Arm1_Total_Dichotomous, Arm2_Events, Arm2_Total_Dichotomous. Leave continuous fields as "NR".
Fields:
{chr(10).join(f"- {f}" for f in OUTCOME_FIELDS)}

STRICT OUTPUT TEMPLATE — follow this format exactly:

[STUDY_INFO]
{chr(10).join(f"{f}: <value or NR>" for f in STUDY_FIELDS)}
[/STUDY_INFO]

[OUTCOME_1]
{chr(10).join(f"{f}: <value or NR>" for f in OUTCOME_FIELDS)}
[/OUTCOME_1]

[OUTCOME_2]
...
[/OUTCOME_2]

(repeat [OUTCOME_N] for every outcome reported in the paper)
"""


# ===========================================================================
# 解析 LLM 输出
# ===========================================================================

def _parse_kv_block(text: str, fields: list[str]) -> dict:
    """从文本块中按字段名提取 key: value"""
    result = {}
    for field in fields:
        pattern = rf"{re.escape(field)}:\s*(.+?)(?:\n|$)"
        match = re.search(pattern, text)
        result[field] = match.group(1).strip() if match else "NR"
    return result


def parse_extraction_output(text: str) -> tuple[dict, list[dict]]:
    """解析完整的 LLM 输出，返回 (study_info, [outcome_dicts])"""
    # 解析 [STUDY_INFO] 块
    study_match = re.search(r"\[STUDY_INFO\](.*?)\[/STUDY_INFO\]", text, re.DOTALL)
    study_info = _parse_kv_block(study_match.group(1), STUDY_FIELDS) if study_match else {f: "NR" for f in STUDY_FIELDS}

    # 解析所有 [OUTCOME_N] 块
    outcome_blocks = re.findall(r"\[OUTCOME_\d+\](.*?)\[/OUTCOME_\d+\]", text, re.DOTALL)
    outcomes = []
    for block in outcome_blocks:
        outcomes.append(_parse_kv_block(block, OUTCOME_FIELDS))

    # 回退：如果没有标签块，尝试直接解析
    if not outcomes and not study_match:
        study_info = _parse_kv_block(text, STUDY_FIELDS)
        outcome = _parse_kv_block(text, OUTCOME_FIELDS)
        if any(v != "NR" for k, v in outcome.items() if k != "Note"):
            outcomes.append(outcome)

    return study_info, outcomes


# ===========================================================================
# DMX API 工具（复用自 WebFullText.py）
# ===========================================================================

def _extract_output_text(resp_json: dict[str, Any]) -> str:
    out_parts = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                t = block.get("text")
                if isinstance(t, str) and t.strip():
                    out_parts.append(t)
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


# ===========================================================================
# 核心处理 — 单篇论文
# ===========================================================================

async def extract_single_paper(client, endpoint, api_key, model_name, paper, system_prompt):
    """从单篇论文 PDF 中提取结构化数据，返回 study_info + outcomes 列表"""
    user_prompt = f"""Extract all data from the paper below according to the STUDY-LEVEL and OUTCOME-LEVEL fields defined in your system instructions.

Input Data:
[Paper ID: {paper['id']}]
[Paper Title: {paper.get('title', '')}]
[PDF Page Images Provided Below]
"""
    prompt = system_prompt + "\n\n" + user_prompt

    pdf_path = Path(paper["pdf_path"])
    if not pdf_path.exists():
        print(f"[DataExtraction] PDF not found for ID {paper['id']}: {pdf_path}")
        return {"id": paper["id"], "study_info": None, "outcomes": [], "error": "PDF not found"}

    try:
        pdf_bytes = pdf_path.read_bytes()
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
    except Exception as e:
        print(f"[DataExtraction] Failed to read PDF for ID {paper['id']}: {e}")
        return {"id": paper["id"], "study_info": None, "outcomes": [], "error": str(e)}

    payload = {
        "model": model_name,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "filename": pdf_path.name,
                     "file_data": f"data:application/pdf;base64,{b64}"},
                    {"type": "input_text", "text": prompt},
                ],
            }
        ],
    }

    try:
        resp = await _call_with_retry(
            _post_with_auth_fallback, client, endpoint, api_key, payload, 300.0
        )
        if resp.status_code != 200:
            print(f"[DataExtraction] API returned {resp.status_code} for ID {paper['id']}")
            return {"id": paper["id"], "study_info": None, "outcomes": [], "error": f"HTTP {resp.status_code}"}

        text = _extract_output_text(resp.json())
        study_info, outcomes = parse_extraction_output(text)
        return {"id": paper["id"], "study_info": study_info, "outcomes": outcomes, "error": None}

    except Exception as e:
        print(f"[DataExtraction] Error for ID {paper['id']}: {e}")
        return {"id": paper["id"], "study_info": None, "outcomes": [], "error": str(e)}


# ===========================================================================
# 异步执行器
# ===========================================================================

async def _run_data_extraction(papers, system_prompt):
    api_key = os.getenv("DMX_API_KEY_1")
    model_name = "gpt-4.1"
    endpoint = "https://www.dmxapi.cn/v1/responses"

    sem = asyncio.Semaphore(5)
    async with httpx.AsyncClient(timeout=300.0) as client:
        async def _bounded(p):
            async with sem:
                return await extract_single_paper(client, endpoint, api_key, model_name, p, system_prompt)

        tasks = [_bounded(p) for p in papers]
        return await asyncio.gather(*tasks)


# ===========================================================================
# 将结果写回 Excel
# ===========================================================================

# Excel 列号 (1-based) 到字段的映射
# A=1 ... AL=38
_COL_MAP: dict[int, str] = {
    # --- 研究级（从 DB 预填） ---
    1:  "_Rayyan_ID",
    2:  "_Title",
    3:  "_Abstract",
    4:  "_Year",
    # --- 研究级（LLM 提取） ---
    5:  "Study_ID",
    6:  "_Full_Text",          # 固定值 "Yes"
    7:  "Trial_Number",
    8:  "Study_Name",
    9:  "Country",
    10: "Number_of_centers",
    11: "Study_Inclusion",
    12: "Exclusion_Criteria",
    13: "Diagnosis",
    14: "Sample_Size",
    15: "Age",
    16: "Gender",
    17: "Follow_up",
    18: "Arm_1_Specific_Regimens",
    19: "Arm1_Drugs",
    20: "Arm2_Specific_Regimens",
    21: "Arm2_Drugs",
    # --- 结局级（LLM 提取） ---
    22: "Outcome_Reported",
    23: "Name_of_Outcome",
    24: "Definition",
    25: "Measurement_Time",
    26: "Arm1_Mean",
    27: "Arm1_SD",
    28: "Arm1_Total_Continuous",
    29: "Arm2_Mean",
    30: "Arm2_SD",
    31: "Arm2_Total_Continuous",
    32: "Arm1_Events",
    33: "Arm1_Total_Dichotomous",
    34: "Arm2_Events",
    35: "Arm2_Total_Dichotomous",
    36: "Note",
    # --- 元数据 ---
    37: "_Extractor",           # 固定值 "AI"
    38: "_Checker",             # 留空
}


def _build_row(paper: dict, study_info: dict | None, outcome: dict | None) -> dict[int, str]:
    """构建一行 Excel 数据，key 为列号 (1-based)"""
    row: dict[int, str] = {}

    # 预填字段（来自数据库 / 固定值）
    row[1] = str(paper.get("id", ""))
    row[2] = paper.get("title", "")
    row[3] = paper.get("abstract", "")
    row[4] = str(paper.get("year", ""))
    row[6] = "Yes"
    row[37] = "AI"
    row[38] = ""

    # 研究级字段
    if study_info:
        for col_num, field_name in _COL_MAP.items():
            if field_name.startswith("_"):
                continue
            if field_name in STUDY_FIELDS and field_name in study_info:
                row[col_num] = study_info[field_name]

    # 结局级字段
    if outcome:
        for col_num, field_name in _COL_MAP.items():
            if field_name in OUTCOME_FIELDS and field_name in outcome:
                row[col_num] = outcome[field_name]

    return row


def write_results_to_excel(
    template_path: Path | str,
    output_path: Path | str,
    papers: list[dict],
    extraction_results: list[dict],
):
    """将提取结果写入 Excel，每个 outcome 一行"""
    wb = openpyxl.load_workbook(template_path)
    ws = wb["baseline characteristics"]

    current_row = 2  # 第 1 行是表头

    for paper, result in zip(papers, extraction_results):
        study_info = result.get("study_info")
        outcomes = result.get("outcomes", [])

        if result.get("error") and not study_info:
            # 提取失败，仍写一行标记错误
            row_data = _build_row(paper, None, None)
            row_data[36] = f"EXTRACTION ERROR: {result['error']}"  # Note 列
            for col_num, value in row_data.items():
                ws.cell(row=current_row, column=col_num, value=value)
            current_row += 1
            continue

        if not outcomes:
            # 没有提取到 outcome，写一行只含研究级信息
            row_data = _build_row(paper, study_info, None)
            for col_num, value in row_data.items():
                ws.cell(row=current_row, column=col_num, value=value)
            current_row += 1
        else:
            # 每个 outcome 一行，研究级字段重复
            for outcome in outcomes:
                row_data = _build_row(paper, study_info, outcome)
                for col_num, value in row_data.items():
                    ws.cell(row=current_row, column=col_num, value=value)
                current_row += 1

    wb.save(output_path)
    wb.close()
    print(f"[DataExtraction] Results saved to {output_path} ({current_row - 2} rows)")


# ===========================================================================
# 对外接口 — 同步包装
# ===========================================================================

def run_data_extraction_sync(
    papers: list[dict],
    template_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict:
    """
    主入口，供 Flask 或脚本调用。

    papers: [{'id', 'title', 'pdf_path', 'abstract'(可选), 'year'(可选), ...}]
    template_path: Excel 模板路径，默认 resources/Templete for data extraction.xlsx
    output_path:   输出 Excel 路径，默认 outputs/data_extraction_result.xlsx

    返回: {'output_path': str, 'total_rows': int, 'results': [...]}
    """
    if template_path is None:
        template_path = TEMPLATE_PATH
    template_path = Path(template_path)

    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "data_extraction_result.xlsx"
    output_path = Path(output_path)

    # 1. 读取模板
    _headers, interventions = load_template_info(template_path)
    system_prompt = build_system_prompt(interventions)

    # 2. 异步提取
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(_run_data_extraction(papers, system_prompt))
    finally:
        loop.close()

    # 3. 写回 Excel
    write_results_to_excel(template_path, output_path, papers, results)

    total_rows = sum(max(len(r.get("outcomes", [])), 1) for r in results)
    return {
        "output_path": str(output_path),
        "total_rows": total_rows,
        "results": results,
    }
