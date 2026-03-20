from __future__ import annotations

import json
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


def _format_review_criteria(project_type: str, pico_dict: Dict[str, str]) -> str:
    pt = (project_type or "").upper()

    if pt == "PECO":
        return "\n".join(
            [
                f"- Population (P): {pico_dict.get('p', '')}",
                f"- Exposure (E): {pico_dict.get('e', '')}",
                f"- Comparison (C): {pico_dict.get('c', '')}",
                f"- Outcome (O): {pico_dict.get('o', '')}",
                f"- Additional Criteria: {pico_dict.get('es', '')}",
            ]
        )

    if pt == "PIRO":
        return "\n".join(
            [
                f"- Population (P): {pico_dict.get('p', '')}",
                f"- Indicator (I): {pico_dict.get('i', '')}",
                f"- Reference (R): {pico_dict.get('r', '')}",
                f"- Outcome (O): {pico_dict.get('o', '')}",
                f"- Additional Criteria: {pico_dict.get('es', '')}",
            ]
        )

    return "\n".join(
        [
            f"- Study Design (S): {pico_dict.get('s', '')}",
            f"- Population (P): {pico_dict.get('p', '')}",
            f"- Intervention (I): {pico_dict.get('i', '')}",
            f"- Comparison (C): {pico_dict.get('c', '')}",
            f"- Outcome (O): {pico_dict.get('o', '')}",
            f"- Additional Criteria: {pico_dict.get('es', '')}",
        ]
    )


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


def get_stage1_prompt(project_type: str, paper_id: int) -> str:
    pt = (project_type or "").upper() or "PICOS"
    return f"""You are running Stage 1: Paper Profiling for a systematic review data extraction pipeline.

Project Type: {pt}
Paper ID: {paper_id}

Return ONLY one raw JSON object with this exact schema:
{{"title": str, "year": str, "journal": str, "authors": str, "study_design": str, "country": str, "sample_size": str, "follow_up": str}}

Rules:
- Return a single JSON object, never an array.
- Use empty strings for fields that are not explicitly reported.
- Extract only from the attached PDF. Do not infer missing values.
- Keep `authors` as a concise author string as reported in the paper.
- Keep `sample_size` and `follow_up` in the paper's own wording when available.
- No markdown fences, no explanation, no extra keys.
"""


def get_stage2_prompt(
    project_type: str,
    pico_dict: Dict[str, str],
    paper_id: int,
    paper_profile: Dict[str, str],
) -> str:
    pt = (project_type or "").upper() or "PICOS"
    criteria = _format_review_criteria(pt, pico_dict)

    return f"""You are running Stage 2: Study-Unit Inventory for a systematic review data extraction pipeline.

Project Type: {pt}
Paper ID: {paper_id}

Paper context from Stage 1:
- Title: {paper_profile.get('title', '')}
- Year: {paper_profile.get('year', '')}
- Journal: {paper_profile.get('journal', '')}
- Authors: {paper_profile.get('authors', '')}
- Study Design: {paper_profile.get('study_design', '')}
- Country: {paper_profile.get('country', '')}
- Sample Size: {paper_profile.get('sample_size', '')}
- Follow-up: {paper_profile.get('follow_up', '')}

Target review criteria:
{criteria}

Return ONLY a raw JSON array with this exact schema:
[{{"unit_id": "SU-1", "label": str, "arms": [str, str], "population_note": str, "intervention": str, "comparison": str}}]

Rules:
- Return one object per independent study unit, sub-study, cohort, or separately reported trial within the paper.
- If the paper reports only one study unit, return exactly one object using `unit_id` = "SU-1".
- Do not split rows by outcome or timepoint. Stage 2 is only for study-unit discovery.
- `arms` should list the compared groups in study order when available. Use empty strings rather than inventing arm names.
- `population_note` should briefly explain what makes this unit distinct (for example subgroup, site, or cohort note).
- No markdown fences, no explanation, no extra keys.
"""


def get_stage3_prompt(
    project_type: str,
    pico_dict: Dict[str, str],
    paper_id: int,
    paper_profile: Dict[str, str],
    study_units: List[Dict[str, object]],
) -> str:
    pt = (project_type or "").upper() or "PICOS"
    criteria = _format_review_criteria(pt, pico_dict)
    study_units_json = json.dumps(study_units, ensure_ascii=False, indent=2)

    return f"""You are running Stage 3: Row Inventory for a systematic review data extraction pipeline.

Project Type: {pt}
Paper ID: {paper_id}

Paper context from Stage 1:
- Title: {paper_profile.get('title', '')}
- Year: {paper_profile.get('year', '')}
- Journal: {paper_profile.get('journal', '')}
- Study Design: {paper_profile.get('study_design', '')}
- Country: {paper_profile.get('country', '')}
- Sample Size: {paper_profile.get('sample_size', '')}
- Follow-up: {paper_profile.get('follow_up', '')}

Target review criteria:
{criteria}

Study units discovered in Stage 2:
{study_units_json}

Return ONLY one raw JSON object with this exact schema:
{{
  "study_units": [
    {{
      "study_unit_id": "SU-1",
      "comparisons": [
        {{
          "comparison_label": str,
          "arms": [str, str],
          "outcomes": [
            {{
              "outcome_name": str,
              "outcome_type": "continuous|binary|other",
              "source_basis": ["text|table|figure"],
              "uncertainty": "low|medium|high",
              "timepoints": [
                {{
                  "timepoint": str,
                  "value_types": [
                    {{
                      "value_type": "endpoint|change_from_baseline|other",
                      "outcome_unit": str,
                      "statistic_description": str,
                      "source_basis": ["text|table|figure"],
                      "uncertainty": "low|medium|high",
                      "evidence_location": str
                    }}
                  ]
                }}
              ]
            }}
          ]
        }}
      ]
    }}
  ],
  "row_candidates": [
    {{
      "row_id": "R-1",
      "study_unit_id": "SU-1",
      "outcome_name": str,
      "outcome_type": "continuous|binary|other",
      "timepoint": str,
      "value_type": "endpoint|change_from_baseline|other",
      "outcome_unit": str,
      "statistic_description": str,
      "source_basis": ["text|table|figure"],
      "uncertainty": "low|medium|high",
      "evidence_location": str,
      "note": str
    }}
  ]
}}

Rules:
- First enumerate study units/comparisons, then outcomes, then timepoints, then value types, and ONLY THEN create `row_candidates`.
- Do not directly jump to final rows without filling the dimension-enumeration structure above.
- One row means: study_unit x outcome x timepoint x value_type.
- Comparison is NOT a row dimension. Arm1 and Arm2 values stay in the same row.
- `study_unit_id` must match one of the Stage 2 unit IDs exactly.
- `row_id` values must be unique within this response.
- Do not output duplicate row candidates for the same study_unit x outcome x timepoint x value_type combination.
- Split different timepoints into separate rows. Do not merge "4, 8, 12 weeks" into one row.
- Distinguish endpoint values from baseline values and change-from-baseline values. Use `value_type = "other"` if the paper is explicit but the category is still unclear.
- If a timepoint is not explicitly reported, use an empty string rather than inventing one.
- Use `continuous` for means/SDs/medians/CI-style measurements, `binary` for event/prevalence/count outcomes, and `other` otherwise.
- `statistic_description` should briefly describe the reported summary style, for example "mean, SD", "mean change, SD", or "events, total".
- `source_basis` must identify where the row was found: one or more of `text`, `table`, `figure`.
- Preserve uncertain items instead of dropping them. Mark uncertainty using `uncertainty = low|medium|high`.
- `evidence_location` should briefly say where the row candidate comes from, for example "Results text", "Table 2", or "Figure 3".
- `note` should stay short and explain only residual ambiguity or disambiguation needs.
- Use empty strings instead of inventing data.
- No markdown fences, no explanation, no extra keys.
"""


def get_stage4_prompt(
    project_type: str,
    paper_id: int,
    paper_profile: Dict[str, str],
    study_unit: Dict[str, object],
    row_candidate: Dict[str, str],
) -> str:
    pt = (project_type or "").upper() or "PICOS"
    study_unit_json = json.dumps(study_unit, ensure_ascii=False, indent=2)
    row_candidate_json = json.dumps(row_candidate, ensure_ascii=False, indent=2)

    return f"""You are running Stage 4: Row Extraction for a systematic review data extraction pipeline.

Project Type: {pt}
Paper ID: {paper_id}

Paper context:
- Title: {paper_profile.get('title', '')}
- Year: {paper_profile.get('year', '')}
- Study Design: {paper_profile.get('study_design', '')}
- Country: {paper_profile.get('country', '')}

Study unit context:
{study_unit_json}

Requested single row candidate:
{row_candidate_json}

Return ONLY one raw JSON object with this exact schema:
{{
  "row_id": "R-1",
  "study_unit_id": "SU-1",
  "outcome_name": str,
  "outcome_type": "continuous|binary|other",
  "timepoint": str,
  "value_type": "endpoint|change_from_baseline|other",
  "outcome_unit": str,
  "statistic_description": str,
  "note": str,
  "values": {{
    "Arm1_Mean": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm1_SD": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm1_Total": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm2_Mean": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm2_SD": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm2_Total": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm1_Events": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}},
    "Arm2_Events": {{"value": str, "evidence_span": str, "evidence_location": str, "confidence": "high|medium|low", "missing_reason": "reported|not_reported|not_applicable|unclear|reported_graphically_only"}}
  }}
}}

Rules:
- Return exactly one object for the requested `row_id`.
- Preserve the requested `row_id`, `study_unit_id`, `outcome_name`, `timepoint`, and `value_type` exactly. Do not merge with any other row.
- Every returned object must include all eight keys inside `values`: `Arm1_Mean`, `Arm1_SD`, `Arm1_Total`, `Arm2_Mean`, `Arm2_SD`, `Arm2_Total`, `Arm1_Events`, `Arm2_Events`.
- Perform field-level extraction. Evaluate each field independently instead of trying to fill the whole row in one shot.
- Arm mapping is strict: Arm1 corresponds to the first arm in `study_unit.arms`; Arm2 corresponds to the second arm. Never swap arms.
- For continuous outcomes, prioritize mean/SD/total style summaries. For binary outcomes, prioritize events/total style summaries. If the paper reports percentages, counts, or `x/y (%)`, capture the exact reported string in the most relevant field rather than inventing a conversion.
- `evidence_span` must be a verbatim quote from the PDF. `evidence_location` should identify where it came from, such as "Results text", "Table 2", or "Figure 1".
- `confidence` must be `high`, `medium`, or `low`.
- `missing_reason` must be one of: `reported`, `not_reported`, `not_applicable`, `unclear`, `reported_graphically_only`.
- For non-applicable fields, return `value = ""` and `missing_reason = "not_applicable"`.
- If a field is mentioned only in a graph or figure without a numeric value, return `value = "Not Reported"` and `missing_reason = "reported_graphically_only"`.
- If an applicable field is not reported numerically, return `value = "Not Reported"` and an empty `evidence_span`.
- Extract only from the attached PDF. Do not infer, impute, or calculate missing values.
- No markdown fences, no explanation, no extra keys.
"""
