import re
from typing import Any


def clean_evidence(text: str) -> str:
    if not text:
        return ""
    return text.strip().strip('"').strip("'")


def extract_evidence(text: str) -> dict[str, str]:
    components = [
        "Study Design",
        "Population",
        "Intervention",
        "Comparison",
        "Outcome",
        "Indicator",
        "Reference",
        "Exposure",
        "Extra",
    ]
    evidences: dict[str, str] = {}

    for component in components:
        pattern = rf"{component}:\s*Matched:\s*(?:Yes|No)\s*Evidence:\s*(.*?)(?=\n[A-Z][a-z]+:|\Z)"
        match = re.search(pattern, text, re.DOTALL)
        evidences[component] = clean_evidence(match.group(1)) if match else ""

    return evidences


def extract_conclusion(text: str) -> str:
    match = re.search(r'Conclusion:\s*\"?(.*?)\"?(?=\n[A-Z][a-z]+:|\Z)', text, re.DOTALL)
    return match.group(1).strip() if match else "No conclusion provided."


def extract_flag(text: str) -> str:
    match = re.search(r"(?mi)^\s*Flag\s*:\s*([01])\s*$", text or "")
    return match.group(1) if match else "0"


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
