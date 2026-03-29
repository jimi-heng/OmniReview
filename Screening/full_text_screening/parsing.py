"""
Structured output parsing utilities for LLM-based screening.

This module is responsible for converting raw LLM outputs into a
strict, validated structured format used by the screening pipeline.

Key responsibilities:
    - Extract JSON from noisy model outputs
    - Validate schema (decision / evidence / reason)
    - Normalize evidence fields across inconsistent model outputs
    - Provide helper extraction functions

Typical LLM output format:
    {
        "decision": "Included" | "Excluded",
        "reason": "...",
        "evidence": {
            "population": "...",
            "intervention": "...",
            ...
        }
    }
"""

import json
from collections.abc import Mapping
from typing import Any


STRUCTURED_EVIDENCE_KEYS = (
    "study_design",
    "population",
    "intervention",
    "comparison",
    "outcomes",
    "additional_criteria",
)


class StructuredOutputError(ValueError):
    """
    Exception raised when LLM output cannot be parsed or validated.

    Attributes:
        raw_output (str): Original model output for debugging.
    """

    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def clean_evidence(text: Any) -> str:
    """
    Normalize evidence text.

    Removes:
        - None values
        - surrounding quotes
        - leading/trailing whitespace

    Args:
        text (Any): Raw evidence value.

    Returns:
        str: Cleaned string.
    """
    if text is None:
        return ""
    return str(text).strip().strip('"').strip("'")


def parse_structured_output(text: str) -> dict[str, Any]:
    """
    Parse structured JSON output from LLM response.

    Steps:
        1. Extract JSON substring
        2. Parse JSON
        3. Validate schema
        4. Normalize evidence fields

    Args:
        text (str): Raw LLM output text.

    Returns:
        dict:
            {
                "decision": str,
                "reason": str,
                "evidence": dict[str, str],
                "raw_payload": dict
            }

    Raises:
        StructuredOutputError:
            If extraction, parsing, or validation fails.
    """
    raw_text = text or ""

    candidate = _extract_json_candidate(raw_text)
    if not candidate:
        raise StructuredOutputError(
            "Model output did not contain a JSON object",
            raw_text,
        )

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(
            f"Model output was not valid JSON: {exc.msg}",
            raw_text,
        ) from exc

    if not isinstance(payload, dict):
        raise StructuredOutputError(
            "Model JSON output must be an object",
            raw_text,
        )

    # === Decision validation ===
    decision = clean_evidence(payload.get("decision"))
    if decision not in {"Included", "Excluded"}:
        raise StructuredOutputError(
            "Model JSON output must set decision to Included or Excluded",
            raw_text,
        )

    # === Evidence validation ===
    evidence_payload = payload.get("evidence") or {}
    if not isinstance(evidence_payload, Mapping):
        raise StructuredOutputError(
            "Model JSON output must provide an evidence object",
            raw_text,
        )

    evidence = _normalize_evidence_dict(evidence_payload)

    # === Reason ===
    reason = clean_evidence(payload.get("reason")) or "No reason provided."

    return {
        "decision": decision,
        "reason": reason,
        "evidence": evidence,
        "raw_payload": payload,
    }


def extract_evidence(text: str) -> dict[str, str]:
    """
    Extract only evidence dictionary from LLM output.

    Args:
        text (str): Raw model output.

    Returns:
        dict[str, str]: Normalized evidence fields.
    """
    return parse_structured_output(text)["evidence"]


def extract_conclusion(text: str) -> str:
    """
    Extract conclusion/reason from LLM output.

    Args:
        text (str): Raw model output.

    Returns:
        str: Reason text.
    """
    return parse_structured_output(text)["reason"]


def extract_output_text(resp_json: dict[str, Any]) -> str:
    """
    Extract textual output from API response JSON.

    Supports structured responses like OpenAI-style output format.

    Args:
        resp_json (dict): Raw API response JSON.

    Returns:
        str: Concatenated output text.
    """
    out_parts: list[str] = []

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


def _extract_json_candidate(text: str) -> str:
    """
    Extract JSON substring from model output.

    Handles:
        - Markdown code blocks (```json ... ```)
        - Extra text before/after JSON
        - Partial formatting noise

    Args:
        text (str): Raw output.

    Returns:
        str: Extracted JSON string or empty string.
    """
    stripped = text.strip()
    if not stripped:
        return ""

    # Remove markdown code fences
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")

    if start == -1 or end == -1 or end < start:
        return ""

    return stripped[start : end + 1]


def _normalize_evidence_dict(payload: Mapping[str, Any]) -> dict[str, str]:
    """
    Normalize evidence dictionary keys.

    Handles alias mapping:
        - "exposure" → "intervention"
        - "reference" → "comparison"
        - etc.

    Args:
        payload (Mapping): Raw evidence dictionary.

    Returns:
        dict[str, str]: Normalized evidence dictionary.
    """
    aliases = {
        "study_design": ("study_design", "design"),
        "population": ("population",),
        "intervention": ("intervention", "exposure", "indicator"),
        "comparison": ("comparison", "comparators", "comparator", "reference"),
        "outcomes": ("outcomes", "outcome"),
        "additional_criteria": ("additional_criteria", "extra", "rules"),
    }

    normalized: dict[str, str] = {}

    for key in STRUCTURED_EVIDENCE_KEYS:
        value = ""
        for alias in aliases[key]:
            if alias in payload:
                value = clean_evidence(payload.get(alias))
                break
        normalized[key] = value

    return normalized