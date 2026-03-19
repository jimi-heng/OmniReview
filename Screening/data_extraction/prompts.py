from __future__ import annotations

from typing import Dict, List


DATA_EXTRACTION_SYSTEM_PROMPT_BASE = """You are an expert medical data extractor for systematic reviews.

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

PICOS_SYSTEM_PROMPT = DATA_EXTRACTION_SYSTEM_PROMPT_BASE + """
Project Type: PICOS (Intervention Studies)
Focus on extracting data related to:
- Study design (RCT, cohort, case-control, etc.)
- Population characteristics
- Intervention details
- Comparison group details
- Outcome measurements
"""

PECO_SYSTEM_PROMPT = DATA_EXTRACTION_SYSTEM_PROMPT_BASE + """
Project Type: PECO (Exposure/Observational Studies)
Focus on extracting data related to:
- Population characteristics
- Exposure factors (risk factors, environmental factors, behaviors, conditions)
- Comparison group details
- Outcome measurements
"""

PIRO_SYSTEM_PROMPT = DATA_EXTRACTION_SYSTEM_PROMPT_BASE + """
Project Type: PIRO (Diagnostic/Prognostic Studies)
Focus on extracting data related to:
- Population characteristics
- Indicator (biomarkers, diagnostic tests, prognostic factors, clinical scores)
- Reference (control group, baseline level, standard diagnostic method, reference measurement)
- Outcome measurements
"""

DEFAULT_PICOS = {"s": "", "p": "", "i": "", "c": "", "o": "", "es": ""}
DEFAULT_PECO = {"p": "", "e": "", "c": "", "o": "", "es": ""}
DEFAULT_PIRO = {"p": "", "i": "", "r": "", "o": "", "es": ""}


def get_system_prompt(project_type: str) -> str:
    prompts = {
        "PICOS": PICOS_SYSTEM_PROMPT,
        "PICO": PICOS_SYSTEM_PROMPT,
        "PECO": PECO_SYSTEM_PROMPT,
        "PIRO": PIRO_SYSTEM_PROMPT,
    }
    return prompts.get((project_type or "").upper(), PICOS_SYSTEM_PROMPT)


def get_default_pico(project_type: str) -> Dict[str, str]:
    defaults = {
        "PICOS": DEFAULT_PICOS,
        "PICO": DEFAULT_PICOS,
        "PECO": DEFAULT_PECO,
        "PIRO": DEFAULT_PIRO,
    }
    return dict(defaults.get((project_type or "").upper(), DEFAULT_PICOS))


def generate_columns_section(llm_columns: List[str]) -> str:
    if not llm_columns:
        return "No specific columns defined. Extract all relevant data."
    return "- " + ", ".join(llm_columns)


def generate_user_prompt(
    project_type: str,
    pico_dict: Dict[str, str],
    columns_section: str,
    paper_id: int,
) -> str:
    pt = (project_type or "").upper()

    if pt == "PECO":
        return f"""Extract the following data fields from the attached PDF.

Target PECO Criteria for this Evaluation:
- Population (P): {pico_dict.get('p', '')}
- Exposure (E): {pico_dict.get('e', '')}
- Comparison (C): {pico_dict.get('c', '')}
- Outcome (O): {pico_dict.get('o', '')}
- Additional Criteria: {pico_dict.get('es', '')}

Data fields to extract:
{columns_section}

MANDATORY OUTPUT FORMAT:
Return a JSON array. EVERY field must use the {{"value": "...", "evidence": "..."}} format.
The "evidence" is the verbatim sentence from the PDF that supports the value.

Paper ID: {paper_id}
"""

    if pt == "PIRO":
        return f"""Extract the following data fields from the attached PDF.

Target PIRO Criteria for this Evaluation:
- Population (P): {pico_dict.get('p', '')}
- Indicator (I): {pico_dict.get('i', '')}
- Reference (R): {pico_dict.get('r', '')}
- Outcome (O): {pico_dict.get('o', '')}
- Additional Criteria: {pico_dict.get('es', '')}

Data fields to extract:
{columns_section}

MANDATORY OUTPUT FORMAT:
Return a JSON array. EVERY field must use the {{"value": "...", "evidence": "..."}} format.
The "evidence" is the verbatim sentence from the PDF that supports the value.

Paper ID: {paper_id}
"""

    return f"""Extract the following data fields from the attached PDF.

Target PICOS Criteria for this Evaluation:
- Study Design (S): {pico_dict.get('s', '')}
- Population (P): {pico_dict.get('p', '')}
- Intervention (I): {pico_dict.get('i', '')}
- Comparison (C): {pico_dict.get('c', '')}
- Outcome (O): {pico_dict.get('o', '')}
- Additional Criteria: {pico_dict.get('es', '')}

Data fields to extract:
{columns_section}

MANDATORY OUTPUT FORMAT:
Return a JSON array. EVERY field must use the {{"value": "...", "evidence": "..."}} format.
The "evidence" is the verbatim sentence from the PDF that supports the value.

Paper ID: {paper_id}
"""

