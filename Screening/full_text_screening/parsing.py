import json
from collections.abc import Mapping
from typing import Any


STRUCTURED_EVIDENCE_KEYS = (
    "study_design",
    "population",
    "intervention",
    "comparison",
    "outcomes",
    "extra_rules",
)


class StructuredOutputError(ValueError):
    def __init__(self, message: str, raw_output: str = "") -> None:
        super().__init__(message)
        self.raw_output = raw_output


def clean_evidence(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip().strip('"').strip("'")


def parse_structured_output(text: str) -> dict[str, Any]:
    raw_text = text or ""
    candidate = _extract_json_candidate(raw_text)
    if not candidate:
        raise StructuredOutputError("Model output did not contain a JSON object", raw_text)

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"Model output was not valid JSON: {exc.msg}", raw_text) from exc

    if not isinstance(payload, dict):
        raise StructuredOutputError("Model JSON output must be an object", raw_text)

    decision = clean_evidence(payload.get("decision"))
    if decision not in {"Included", "Excluded"}:
        raise StructuredOutputError("Model JSON output must set decision to Included or Excluded", raw_text)

    evidence_payload = payload.get("evidence")
    if evidence_payload is None:
        evidence_payload = {}
    if not isinstance(evidence_payload, Mapping):
        raise StructuredOutputError("Model JSON output must provide an evidence object", raw_text)

    evidence = _normalize_evidence_dict(evidence_payload)
    reason = clean_evidence(payload.get("reason")) or "No reason provided."
    return {
        "decision": decision,
        "reason": reason,
        "evidence": evidence,
        "raw_payload": payload,
    }


def extract_evidence(text: str) -> dict[str, str]:
    return parse_structured_output(text)["evidence"]


def extract_conclusion(text: str) -> str:
    return parse_structured_output(text)["reason"]


def extract_output_text(resp_json: dict[str, Any]) -> str:
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
    stripped = text.strip()
    if not stripped:
        return ""
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
    aliases = {
        "study_design": ("study_design", "design"),
        "population": ("population",),
        "intervention": ("intervention", "exposure", "indicator"),
        "comparison": ("comparison", "comparators", "comparator", "reference"),
        "outcomes": ("outcomes", "outcome"),
        "extra_rules": ("extra_rules", "extra", "rules"),
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
