from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .models import ExtractedCell, ExtractionRow, RowCandidate


CANONICAL_VALUE_FIELDS = [
    "Arm1_Mean",
    "Arm1_SD",
    "Arm1_Total",
    "Arm2_Mean",
    "Arm2_SD",
    "Arm2_Total",
    "Arm1_Events",
    "Arm2_Events",
]

CONTINUOUS_ONLY_FIELDS = {"Arm1_Mean", "Arm1_SD", "Arm2_Mean", "Arm2_SD"}
BINARY_ONLY_FIELDS = {"Arm1_Events", "Arm2_Events"}


class RobustJSONParser:
    """Robust JSON parser with fallback strategies plus typed helpers."""

    @staticmethod
    def parse(text: str, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        parsed = RobustJSONParser.parse_json_payload(text)
        return RobustJSONParser._process_parsed(parsed, columns)

    @staticmethod
    def parse_json_payload(text: str) -> Any:
        if not text or not text.strip():
            raise ValueError("Empty model output")

        for parser in (
            RobustJSONParser._try_direct_parse,
            RobustJSONParser._try_markdown_parse,
            RobustJSONParser._try_brace_parse,
            RobustJSONParser._try_repair_parse,
        ):
            parsed = parser(text)
            if parsed is not None:
                return parsed

        raise ValueError("No valid JSON found in response")

    @staticmethod
    def parse_row_candidates(text: str) -> List[RowCandidate]:
        parsed = RobustJSONParser.parse_json_payload(text)
        if isinstance(parsed, dict):
            rows = [parsed]
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ValueError("Stage 3 JSON root must be object or array")

        candidates: List[RowCandidate] = []
        for index, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue

            outcome_name = RobustJSONParser._normalize_text(item.get("outcome_name"))
            if not outcome_name:
                continue

            candidates.append(
                RowCandidate(
                    row_id=RobustJSONParser._normalize_text(item.get("row_id")) or f"R-{index}",
                    study_unit_id=RobustJSONParser._normalize_text(item.get("study_unit_id")) or "SU-1",
                    outcome_name=outcome_name,
                    outcome_type=RobustJSONParser._normalize_outcome_type(item.get("outcome_type")),
                    timepoint=RobustJSONParser._normalize_text(item.get("timepoint")),
                    value_type=RobustJSONParser._normalize_value_type(item.get("value_type")),
                    outcome_unit=RobustJSONParser._normalize_text(item.get("outcome_unit")),
                    statistic_description=RobustJSONParser._normalize_text(item.get("statistic_description")),
                    note=RobustJSONParser._normalize_text(item.get("note")),
                )
            )

        if not candidates:
            raise ValueError("Stage 3 returned no valid row candidates")
        return candidates

    @staticmethod
    def normalize_row_candidates(
        row_candidates: List[RowCandidate],
        *,
        valid_study_unit_ids: List[str] | None = None,
    ) -> List[RowCandidate]:
        valid_ids = [unit_id.strip() for unit_id in (valid_study_unit_ids or []) if isinstance(unit_id, str) and unit_id.strip()]
        default_unit_id = valid_ids[0] if valid_ids else "SU-1"
        deduped: Dict[tuple[str, str, str, str], RowCandidate] = {}

        for candidate in row_candidates:
            study_unit_id = RobustJSONParser._normalize_text(candidate.study_unit_id) or default_unit_id
            if valid_ids and study_unit_id not in valid_ids:
                if len(valid_ids) == 1:
                    study_unit_id = default_unit_id
                else:
                    continue

            normalized = RowCandidate(
                row_id="",
                study_unit_id=study_unit_id,
                outcome_name=RobustJSONParser._clean_whitespace(candidate.outcome_name),
                outcome_type=RobustJSONParser._normalize_outcome_type(candidate.outcome_type),
                timepoint=RobustJSONParser._clean_whitespace(candidate.timepoint),
                value_type=RobustJSONParser._normalize_value_type(candidate.value_type) or "other",
                outcome_unit=RobustJSONParser._clean_whitespace(candidate.outcome_unit),
                statistic_description=RobustJSONParser._clean_whitespace(candidate.statistic_description),
                note=RobustJSONParser._clean_whitespace(candidate.note),
            )
            if not normalized.outcome_name:
                continue

            signature = (
                normalized.study_unit_id,
                normalized.outcome_name.casefold(),
                normalized.timepoint.casefold(),
                normalized.value_type.casefold(),
            )

            existing = deduped.get(signature)
            if existing is None:
                deduped[signature] = normalized
                continue

            deduped[signature] = RowCandidate(
                row_id="",
                study_unit_id=existing.study_unit_id,
                outcome_name=existing.outcome_name,
                outcome_type=existing.outcome_type if existing.outcome_type != "other" else normalized.outcome_type,
                timepoint=existing.timepoint or normalized.timepoint,
                value_type=existing.value_type if existing.value_type != "other" else normalized.value_type,
                outcome_unit=existing.outcome_unit or normalized.outcome_unit,
                statistic_description=existing.statistic_description or normalized.statistic_description,
                note=existing.note or normalized.note,
            )

        finalized = [
            RowCandidate(
                row_id=f"R-{index}",
                study_unit_id=candidate.study_unit_id,
                outcome_name=candidate.outcome_name,
                outcome_type=candidate.outcome_type,
                timepoint=candidate.timepoint,
                value_type=candidate.value_type,
                outcome_unit=candidate.outcome_unit,
                statistic_description=candidate.statistic_description,
                note=candidate.note,
            )
            for index, candidate in enumerate(deduped.values(), start=1)
        ]

        if not finalized:
            raise ValueError("Stage 3 normalization removed all row candidates")
        return finalized

    @staticmethod
    def parse_extraction_rows(text: str, row_candidates: List[RowCandidate]) -> List[ExtractionRow]:
        parsed = RobustJSONParser.parse_json_payload(text)
        if isinstance(parsed, dict):
            rows = [parsed]
        elif isinstance(parsed, list):
            rows = parsed
        else:
            raise ValueError("Stage 4 JSON root must be object or array")

        by_row_id = {candidate.row_id: candidate for candidate in row_candidates}
        extraction_rows: List[ExtractionRow] = []

        for index, item in enumerate(rows):
            if not isinstance(item, dict):
                continue

            fallback_candidate = row_candidates[index] if index < len(row_candidates) else None
            row_id = RobustJSONParser._normalize_text(item.get("row_id")) or getattr(fallback_candidate, "row_id", "")
            if not row_id:
                continue

            candidate = by_row_id.get(row_id)
            outcome_type = RobustJSONParser._normalize_outcome_type(
                item.get("outcome_type") if item.get("outcome_type") is not None else getattr(candidate, "outcome_type", "")
            )
            raw_values = item.get("values", {})
            if not isinstance(raw_values, dict):
                raw_values = {}

            values: Dict[str, ExtractedCell] = {}
            for field_name in CANONICAL_VALUE_FIELDS:
                default_value = RobustJSONParser._default_field_value(outcome_type, field_name)
                cell = raw_values.get(field_name)
                if isinstance(cell, dict):
                    values[field_name] = ExtractedCell(
                        value=RobustJSONParser._normalize_cell_value(cell.get("value"), default_value),
                        evidence=RobustJSONParser._clean_whitespace(cell.get("evidence")),
                    )
                elif cell is None:
                    values[field_name] = ExtractedCell(value=default_value, evidence="")
                else:
                    values[field_name] = ExtractedCell(
                        value=RobustJSONParser._normalize_cell_value(cell, default_value),
                        evidence="",
                    )

            extraction_rows.append(
                ExtractionRow(
                    row_id=row_id,
                    study_unit_id=RobustJSONParser._normalize_text(item.get("study_unit_id"))
                    or getattr(candidate, "study_unit_id", "SU-1"),
                    outcome_name=RobustJSONParser._normalize_text(item.get("outcome_name"))
                    or getattr(candidate, "outcome_name", ""),
                    outcome_type=outcome_type,
                    timepoint=RobustJSONParser._normalize_text(item.get("timepoint")) or getattr(candidate, "timepoint", ""),
                    value_type=RobustJSONParser._normalize_value_type(item.get("value_type"))
                    or getattr(candidate, "value_type", ""),
                    outcome_unit=RobustJSONParser._normalize_text(item.get("outcome_unit"))
                    or getattr(candidate, "outcome_unit", ""),
                    statistic_description=RobustJSONParser._normalize_text(item.get("statistic_description"))
                    or getattr(candidate, "statistic_description", ""),
                    note=RobustJSONParser._normalize_text(item.get("note")) or getattr(candidate, "note", ""),
                    values=values,
                    error=RobustJSONParser._normalize_text(item.get("error")),
                )
            )

        if not extraction_rows:
            raise ValueError("Stage 4 returned no valid extraction rows")
        return extraction_rows

    @staticmethod
    def normalize_extraction_rows(
        extraction_rows: List[ExtractionRow],
        row_candidates: List[RowCandidate],
    ) -> List[ExtractionRow]:
        candidate_by_id = {candidate.row_id: candidate for candidate in row_candidates}
        normalized_by_id: Dict[str, ExtractionRow] = {}

        for extraction_row in extraction_rows:
            candidate = candidate_by_id.get(extraction_row.row_id)
            if candidate is None:
                continue

            normalized_row = RobustJSONParser._normalize_extraction_row(extraction_row, candidate)
            existing = normalized_by_id.get(candidate.row_id)
            if existing is None:
                normalized_by_id[candidate.row_id] = normalized_row
            else:
                normalized_by_id[candidate.row_id] = RobustJSONParser._merge_extraction_rows(
                    existing,
                    normalized_row,
                    candidate,
                )

        ordered_rows = []
        for candidate in row_candidates:
            ordered_rows.append(
                normalized_by_id.get(
                    candidate.row_id,
                    RobustJSONParser._blank_extraction_row(candidate, error="Missing from Stage 4 output."),
                )
            )
        return ordered_rows

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
                values[col] = RobustJSONParser._normalize_flat_value(cell.get("value", "Not Reported"))
                ev = cell.get("evidence", "")
                if isinstance(ev, str) and ev.strip():
                    evidences[col] = ev.strip()
            else:
                values[col] = RobustJSONParser._normalize_flat_value(cell)

        return values, evidences

    @staticmethod
    def _normalize_outcome_type(value: Any) -> str:
        text = RobustJSONParser._normalize_text(value).lower()
        if text in {"continuous", "binary", "other"}:
            return text
        if text in {"dichotomous", "event"}:
            return "binary"
        return "other"

    @staticmethod
    def _normalize_value_type(value: Any) -> str:
        text = RobustJSONParser._normalize_text(value).lower()
        if not text:
            return "other"
        aliases = {
            "endpoint": "endpoint",
            "endpoint_value": "endpoint",
            "final_value": "endpoint",
            "change": "change_from_baseline",
            "change_from_baseline": "change_from_baseline",
            "delta": "change_from_baseline",
            "other": "other",
        }
        return aliases.get(text, text)

    @staticmethod
    def _normalize_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value).strip()

    @staticmethod
    def _clean_whitespace(value: Any) -> str:
        text = RobustJSONParser._normalize_text(value)
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _normalize_flat_value(value: Any) -> str:
        if value is None:
            return "Not Reported"
        if isinstance(value, str):
            return value.strip() if value.strip() else "Not Reported"
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _normalize_cell_value(value: Any, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, str):
            normalized = RobustJSONParser._clean_whitespace(value)
            return normalized if normalized else default
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    @staticmethod
    def _default_field_value(outcome_type: str, field_name: str) -> str:
        if outcome_type == "continuous" and field_name in BINARY_ONLY_FIELDS:
            return ""
        if outcome_type == "binary" and field_name in CONTINUOUS_ONLY_FIELDS:
            return ""
        return "Not Reported"

    @staticmethod
    def _normalize_extraction_row(extraction_row: ExtractionRow, candidate: RowCandidate) -> ExtractionRow:
        outcome_type = candidate.outcome_type if candidate.outcome_type != "other" else extraction_row.outcome_type
        if outcome_type == "other" and extraction_row.outcome_type != "other":
            outcome_type = extraction_row.outcome_type

        values: Dict[str, ExtractedCell] = {}
        for field_name in CANONICAL_VALUE_FIELDS:
            default_value = RobustJSONParser._default_field_value(outcome_type, field_name)
            raw_cell = extraction_row.values.get(field_name, ExtractedCell(value=default_value, evidence=""))
            if default_value == "":
                values[field_name] = ExtractedCell(value="", evidence="")
                continue

            values[field_name] = ExtractedCell(
                value=RobustJSONParser._normalize_cell_value(raw_cell.value, default_value),
                evidence=RobustJSONParser._clean_whitespace(raw_cell.evidence),
            )

        return ExtractionRow(
            row_id=candidate.row_id,
            study_unit_id=candidate.study_unit_id,
            outcome_name=candidate.outcome_name,
            outcome_type=outcome_type,
            timepoint=candidate.timepoint or RobustJSONParser._clean_whitespace(extraction_row.timepoint),
            value_type=candidate.value_type or RobustJSONParser._normalize_value_type(extraction_row.value_type) or "other",
            outcome_unit=candidate.outcome_unit or RobustJSONParser._clean_whitespace(extraction_row.outcome_unit),
            statistic_description=candidate.statistic_description
            or RobustJSONParser._clean_whitespace(extraction_row.statistic_description),
            note=RobustJSONParser._merge_notes(candidate.note, extraction_row.note),
            values=values,
            error=RobustJSONParser._clean_whitespace(extraction_row.error),
        )

    @staticmethod
    def _merge_extraction_rows(
        existing: ExtractionRow,
        incoming: ExtractionRow,
        candidate: RowCandidate,
    ) -> ExtractionRow:
        outcome_type = existing.outcome_type if existing.outcome_type != "other" else incoming.outcome_type
        values: Dict[str, ExtractedCell] = {}
        for field_name in CANONICAL_VALUE_FIELDS:
            values[field_name] = RobustJSONParser._merge_cells(
                existing.values.get(field_name, ExtractedCell()),
                incoming.values.get(field_name, ExtractedCell()),
                outcome_type=outcome_type,
                field_name=field_name,
            )

        return ExtractionRow(
            row_id=candidate.row_id,
            study_unit_id=candidate.study_unit_id,
            outcome_name=candidate.outcome_name,
            outcome_type=outcome_type,
            timepoint=existing.timepoint or incoming.timepoint,
            value_type=existing.value_type if existing.value_type != "other" else incoming.value_type,
            outcome_unit=existing.outcome_unit or incoming.outcome_unit,
            statistic_description=existing.statistic_description or incoming.statistic_description,
            note=RobustJSONParser._merge_notes(existing.note, incoming.note),
            values=values,
            error=RobustJSONParser._merge_notes(existing.error, incoming.error),
        )

    @staticmethod
    def _merge_cells(
        existing: ExtractedCell,
        incoming: ExtractedCell,
        *,
        outcome_type: str,
        field_name: str,
    ) -> ExtractedCell:
        default_value = RobustJSONParser._default_field_value(outcome_type, field_name)
        if default_value == "":
            return ExtractedCell(value="", evidence="")

        existing_score = RobustJSONParser._cell_score(existing, default_value)
        incoming_score = RobustJSONParser._cell_score(incoming, default_value)
        if incoming_score > existing_score:
            return ExtractedCell(
                value=RobustJSONParser._normalize_cell_value(incoming.value, default_value),
                evidence=RobustJSONParser._clean_whitespace(incoming.evidence),
            )
        if existing_score > incoming_score:
            return ExtractedCell(
                value=RobustJSONParser._normalize_cell_value(existing.value, default_value),
                evidence=RobustJSONParser._clean_whitespace(existing.evidence),
            )

        existing_evidence = RobustJSONParser._clean_whitespace(existing.evidence)
        incoming_evidence = RobustJSONParser._clean_whitespace(incoming.evidence)
        if len(incoming_evidence) > len(existing_evidence):
            return ExtractedCell(
                value=RobustJSONParser._normalize_cell_value(incoming.value, default_value),
                evidence=incoming_evidence,
            )
        return ExtractedCell(
            value=RobustJSONParser._normalize_cell_value(existing.value, default_value),
            evidence=existing_evidence,
        )

    @staticmethod
    def _cell_score(cell: ExtractedCell, default_value: str) -> int:
        value = RobustJSONParser._normalize_cell_value(cell.value, default_value)
        evidence = RobustJSONParser._clean_whitespace(cell.evidence)
        if value != default_value and evidence:
            return 3
        if value != default_value:
            return 2
        if evidence:
            return 1
        return 0

    @staticmethod
    def _merge_notes(primary: str, secondary: str) -> str:
        left = RobustJSONParser._clean_whitespace(primary)
        right = RobustJSONParser._clean_whitespace(secondary)
        if not left:
            return right
        if not right or right == left:
            return left
        return f"{left} | {right}"

    @staticmethod
    def _blank_extraction_row(candidate: RowCandidate, *, error: str = "") -> ExtractionRow:
        values: Dict[str, ExtractedCell] = {}
        for field_name in CANONICAL_VALUE_FIELDS:
            default_value = RobustJSONParser._default_field_value(candidate.outcome_type, field_name)
            values[field_name] = ExtractedCell(value=default_value, evidence="")

        return ExtractionRow(
            row_id=candidate.row_id,
            study_unit_id=candidate.study_unit_id,
            outcome_name=candidate.outcome_name,
            outcome_type=candidate.outcome_type,
            timepoint=candidate.timepoint,
            value_type=candidate.value_type,
            outcome_unit=candidate.outcome_unit,
            statistic_description=candidate.statistic_description,
            note=candidate.note,
            values=values,
            error=error,
        )
