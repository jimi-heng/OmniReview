from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


class RobustJSONParser:
    """Robust JSON parser with multiple fallback strategies."""

    @staticmethod
    def parse(text: str, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        if not text or not text.strip():
            raise ValueError("Empty model output")

        parsed = RobustJSONParser._try_direct_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        parsed = RobustJSONParser._try_markdown_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        parsed = RobustJSONParser._try_brace_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        parsed = RobustJSONParser._try_repair_parse(text)
        if parsed is not None:
            return RobustJSONParser._process_parsed(parsed, columns)

        raise ValueError("No valid JSON found in response")

    @staticmethod
    def _try_direct_parse(text: str) -> Optional[Any]:
        stripped = text.strip()
        if stripped.startswith("```json"):
            stripped = stripped[7:].strip()
        elif stripped.startswith("```"):
            stripped = stripped[3:].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()

        try:
            return json.loads(stripped, strict=False)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _try_markdown_parse(text: str) -> Optional[Any]:
        patterns = [r"```json\s*\n(.*?)\n```", r"```\s*\n(.*?)\n```"]
        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match, strict=False)
                except json.JSONDecodeError:
                    continue
        return None

    @staticmethod
    def _try_brace_parse(text: str) -> Optional[Any]:
        start_match = re.search(r"[\[{]", text)
        if not start_match:
            return None

        start = start_match.start()
        end_arr = text.rfind("]")
        end_obj = text.rfind("}")
        end = max(end_arr, end_obj)
        if end < start:
            return None

        candidate = text[start : end + 1]
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _try_repair_parse(text: str) -> Optional[Any]:
        stripped = text.strip()
        first_brace = stripped.find("{")
        if first_brace < 0:
            return None

        json_text = stripped[first_brace:]
        repaired = RobustJSONParser._repair_truncated(json_text)
        if repaired is not None:
            try:
                return json.loads(repaired, strict=False)
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _repair_truncated(text: str) -> Optional[str]:
        open_braces = 0
        open_brackets = 0
        in_string = False
        escape_next = False

        for char in text:
            if escape_next:
                escape_next = False
                continue
            if char == "\\" and in_string:
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "{":
                open_braces += 1
            elif char == "}":
                open_braces -= 1
            elif char == "[":
                open_brackets += 1
            elif char == "]":
                open_brackets -= 1

        if open_braces <= 0 and open_brackets <= 0:
            return text

        repaired = text.rstrip()
        if in_string:
            last_quote = repaired.rfind('"')
            if last_quote > 0:
                repaired = repaired[: last_quote + 1]

        repaired = repaired.rstrip().rstrip(",")
        repaired += "]" * max(0, open_brackets)
        repaired += "}" * max(0, open_braces)
        return repaired

    @staticmethod
    def _process_parsed(parsed: Any, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        if isinstance(parsed, dict):
            rows = [parsed]
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ValueError("JSON root must be object or array")

        value_rows: List[Dict[str, str]] = []
        evidence_rows: List[Dict[str, str]] = []

        for item in rows:
            if not isinstance(item, dict):
                continue
            values, evidences = RobustJSONParser._split_nested_row(item, columns)
            value_rows.append(values)
            evidence_rows.append(evidences)

        if not value_rows:
            raise ValueError("No valid row objects in JSON")
        return value_rows, evidence_rows

    @staticmethod
    def _split_nested_row(row: Dict[str, Any], columns: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
        values: Dict[str, str] = {}
        evidences: Dict[str, str] = {}

        for col in columns:
            cell = row.get(col, "Not Reported")
            if isinstance(cell, dict):
                values[col] = RobustJSONParser._normalize_value(cell.get("value", "Not Reported"))
                ev = cell.get("evidence", "")
                if isinstance(ev, str) and ev.strip():
                    evidences[col] = ev.strip()
            else:
                values[col] = RobustJSONParser._normalize_value(cell)

        return values, evidences

    @staticmethod
    def _normalize_value(value: Any) -> str:
        if value is None:
            return "Not Reported"
        if isinstance(value, str):
            return value.strip() if value.strip() else "Not Reported"
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)
