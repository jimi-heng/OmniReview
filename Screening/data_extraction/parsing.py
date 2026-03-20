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

TIME_UNIT_ALIASES = {
    "d": "day",
    "day": "day",
    "days": "day",
    "wk": "week",
    "wks": "week",
    "week": "week",
    "weeks": "week",
    "mo": "month",
    "mos": "month",
    "month": "month",
    "months": "month",
    "yr": "year",
    "yrs": "year",
    "year": "year",
    "years": "year",
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "hours": "hour",
}

OUTCOME_NAME_ALIASES = {
    "haemoglobin": "Hemoglobin",
    "hemoglobin": "Hemoglobin",
    "hb": "Hb",
}

STATISTIC_DESCRIPTION_ALIASES = {
    "mean sd": "mean, SD",
    "mean,sd": "mean, SD",
    "mean and sd": "mean, SD",
    "mean(sd)": "mean, SD",
    "events total": "events, total",
    "events,total": "events, total",
    "events and total": "events, total",
}

_EFFECT_ONLY_OUTCOME_NAMES = {
    "rr",
    "relative risk",
    "risk ratio",
    "or",
    "odds ratio",
    "hr",
    "hazard ratio",
    "rrr",
    "arr",
    "nnt",
    "nnh",
    "risk difference",
    "mean difference",
    "standardized mean difference",
    "smd",
    "md",
}


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
        rows = RobustJSONParser._extract_stage3_row_candidate_items(parsed)

        candidates: List[RowCandidate] = []
        for index, item in enumerate(rows, start=1):
            if not isinstance(item, dict):
                continue

            outcome_name = RobustJSONParser._normalize_outcome_name(
                item.get("outcome_name") or item.get("outcome") or item.get("name")
            )
            if not outcome_name:
                continue

            note = RobustJSONParser._build_stage3_candidate_note(item)
            candidates.append(
                RowCandidate(
                    row_id=RobustJSONParser._normalize_text(item.get("row_id")) or f"R-{index}",
                    study_unit_id=RobustJSONParser._normalize_study_unit_id(item.get("study_unit_id")) or "SU-1",
                    outcome_name=outcome_name,
                    outcome_type=RobustJSONParser._normalize_outcome_type(
                        item.get("outcome_type"),
                        statistic_description=item.get("statistic_description"),
                    ),
                    timepoint=RobustJSONParser._normalize_timepoint(item.get("timepoint")),
                    value_type=RobustJSONParser._normalize_value_type(item.get("value_type")),
                    outcome_unit=RobustJSONParser._normalize_text(item.get("outcome_unit")),
                    statistic_description=RobustJSONParser._normalize_statistic_description(
                        item.get("statistic_description")
                    ),
                    note=note,
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
        valid_id_lookup = {unit_id.casefold(): unit_id for unit_id in valid_ids}
        default_unit_id = valid_ids[0] if valid_ids else "SU-1"
        deduped: Dict[tuple[str, str, str, str], RowCandidate] = {}

        for candidate in row_candidates:
            study_unit_id = RobustJSONParser._normalize_study_unit_id(candidate.study_unit_id) or default_unit_id
            if valid_id_lookup:
                matched = valid_id_lookup.get(study_unit_id.casefold())
                if matched:
                    study_unit_id = matched
                elif len(valid_ids) == 1:
                    study_unit_id = default_unit_id
                else:
                    continue

            normalized_outcome_name = RobustJSONParser._normalize_outcome_name(candidate.outcome_name)
            normalized_timepoint = RobustJSONParser._normalize_timepoint(candidate.timepoint)
            normalized_statistic_description = RobustJSONParser._normalize_statistic_description(
                candidate.statistic_description
            )
            normalized_value_type = RobustJSONParser._normalize_value_type(candidate.value_type)
            normalized_outcome_type = RobustJSONParser._normalize_outcome_type(
                candidate.outcome_type,
                statistic_description=normalized_statistic_description,
            )

            normalized = RowCandidate(
                row_id="",
                study_unit_id=study_unit_id,
                outcome_name=normalized_outcome_name,
                outcome_type=normalized_outcome_type,
                timepoint=normalized_timepoint,
                value_type=normalized_value_type or "other",
                outcome_unit=RobustJSONParser._clean_whitespace(candidate.outcome_unit),
                statistic_description=normalized_statistic_description,
                note=RobustJSONParser._clean_whitespace(candidate.note),
            )
            if not normalized.outcome_name:
                continue
            if RobustJSONParser._is_effect_only_row_candidate(normalized):
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
                outcome_type=RobustJSONParser._prefer_outcome_type(existing.outcome_type, normalized.outcome_type),
                timepoint=existing.timepoint or normalized.timepoint,
                value_type=RobustJSONParser._prefer_value_type(existing.value_type, normalized.value_type),
                outcome_unit=existing.outcome_unit or normalized.outcome_unit,
                statistic_description=existing.statistic_description or normalized.statistic_description,
                note=RobustJSONParser._merge_notes(existing.note, normalized.note),
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
                item.get("outcome_type") if item.get("outcome_type") is not None else getattr(candidate, "outcome_type", ""),
                statistic_description=item.get("statistic_description"),
            )
            raw_values = item.get("values", {})
            if not isinstance(raw_values, dict):
                raw_values = {
                    field_name: item.get(field_name)
                    for field_name in CANONICAL_VALUE_FIELDS
                    if item.get(field_name) is not None
                }

            values: Dict[str, ExtractedCell] = {}
            metadata_note_parts: List[str] = []
            for field_name in CANONICAL_VALUE_FIELDS:
                default_value = RobustJSONParser._default_field_value(outcome_type, field_name)
                cell = raw_values.get(field_name)
                parsed_cell, metadata_fragment = RobustJSONParser._parse_stage4_value_cell(
                    cell,
                    field_name=field_name,
                    default_value=default_value,
                )
                values[field_name] = parsed_cell
                if metadata_fragment:
                    metadata_note_parts.append(metadata_fragment)

            values = RobustJSONParser._normalize_row_value_cells(values)
            candidate_note_fragments: List[str] = []
            if candidate is not None:
                returned_outcome_name = RobustJSONParser._normalize_outcome_name(item.get("outcome_name"))
                if returned_outcome_name and returned_outcome_name.casefold() != candidate.outcome_name.casefold():
                    candidate_note_fragments.append(f"candidate_outcome_mismatch={returned_outcome_name}")

                returned_timepoint = RobustJSONParser._normalize_timepoint(item.get("timepoint"))
                candidate_timepoint = RobustJSONParser._normalize_timepoint(candidate.timepoint)
                if returned_timepoint and returned_timepoint.casefold() != candidate_timepoint.casefold():
                    candidate_note_fragments.append(f"candidate_timepoint_mismatch={returned_timepoint}")

            normalized_note = RobustJSONParser._merge_notes(
                RobustJSONParser._normalize_text(item.get("note")),
                " | ".join(metadata_note_parts + candidate_note_fragments),
            )

            extraction_rows.append(
                ExtractionRow(
                    row_id=row_id,
                    study_unit_id=RobustJSONParser._normalize_study_unit_id(item.get("study_unit_id"))
                    or getattr(candidate, "study_unit_id", "SU-1"),
                    outcome_name=RobustJSONParser._normalize_outcome_name(item.get("outcome_name"))
                    or getattr(candidate, "outcome_name", ""),
                    outcome_type=outcome_type,
                    timepoint=RobustJSONParser._normalize_timepoint(item.get("timepoint"))
                    or getattr(candidate, "timepoint", ""),
                    value_type=RobustJSONParser._normalize_value_type(item.get("value_type"))
                    or getattr(candidate, "value_type", ""),
                    outcome_unit=RobustJSONParser._normalize_text(item.get("outcome_unit"))
                    or getattr(candidate, "outcome_unit", ""),
                    statistic_description=RobustJSONParser._normalize_statistic_description(item.get("statistic_description"))
                    or getattr(candidate, "statistic_description", ""),
                    note=normalized_note or getattr(candidate, "note", ""),
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
    def _extract_stage3_row_candidate_items(parsed: Any) -> List[Dict[str, Any]]:
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if not isinstance(parsed, dict):
            raise ValueError("Stage 3 JSON root must be object or array")

        direct_candidates = parsed.get("row_candidates") or parsed.get("rows")
        if isinstance(direct_candidates, list):
            return [item for item in direct_candidates if isinstance(item, dict)]

        if "outcome_name" in parsed or "outcome" in parsed:
            return [parsed]

        collected: List[Dict[str, Any]] = []
        for value in parsed.values():
            if isinstance(value, dict):
                collected.extend(RobustJSONParser._collect_stage3_row_candidate_items(value))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        if "outcome_name" in item or "outcome" in item:
                            collected.append(item)
                        else:
                            collected.extend(RobustJSONParser._collect_stage3_row_candidate_items(item))
        if collected:
            return collected
        raise ValueError("Stage 3 JSON root must contain row_candidates or row-like objects")

    @staticmethod
    def _collect_stage3_row_candidate_items(parsed: Any) -> List[Dict[str, Any]]:
        try:
            return RobustJSONParser._extract_stage3_row_candidate_items(parsed)
        except ValueError:
            return []

    @staticmethod
    def _build_stage3_candidate_note(item: Dict[str, Any]) -> str:
        note = RobustJSONParser._normalize_text(item.get("note"))
        source_basis = RobustJSONParser._normalize_source_basis(item.get("source_basis") or item.get("source"))
        uncertainty = RobustJSONParser._normalize_uncertainty(item.get("uncertainty"))
        evidence_location = RobustJSONParser._normalize_text(item.get("evidence_location"))
        metadata_parts: List[str] = []
        if source_basis:
            metadata_parts.append(f"source={'+'.join(source_basis)}")
        if uncertainty:
            metadata_parts.append(f"uncertainty={uncertainty}")
        if evidence_location:
            metadata_parts.append(f"location={evidence_location}")
        return RobustJSONParser._merge_notes(note, "; ".join(metadata_parts))

    @staticmethod
    def _parse_stage4_value_cell(
        cell: Any,
        *,
        field_name: str,
        default_value: str,
    ) -> Tuple[ExtractedCell, str]:
        if isinstance(cell, dict):
            missing_reason = RobustJSONParser._normalize_missing_reason(cell.get("missing_reason"))
            confidence = RobustJSONParser._normalize_confidence(cell.get("confidence"))
            evidence_span = RobustJSONParser._clean_whitespace(
                cell.get("evidence_span") if cell.get("evidence_span") is not None else cell.get("evidence")
            )
            evidence_location = RobustJSONParser._clean_whitespace(cell.get("evidence_location"))
            normalized_value = RobustJSONParser._normalize_stage4_field_value(
                cell.get("value"),
                default_value=default_value,
                missing_reason=missing_reason,
            )
            metadata = RobustJSONParser._build_field_metadata_fragment(
                field_name=field_name,
                missing_reason=missing_reason,
                confidence=confidence,
                evidence_location=evidence_location,
            )
            return ExtractedCell(value=normalized_value, evidence=evidence_span), metadata

        if cell is None:
            return ExtractedCell(value=default_value, evidence=""), ""

        return ExtractedCell(
            value=RobustJSONParser._normalize_stage4_field_value(
                cell,
                default_value=default_value,
                missing_reason="",
            ),
            evidence="",
        ), ""

    @staticmethod
    def _normalize_row_value_cells(values: Dict[str, ExtractedCell]) -> Dict[str, ExtractedCell]:
        normalized = {
            field_name: ExtractedCell(
                value=RobustJSONParser._clean_whitespace(cell.value),
                evidence=RobustJSONParser._clean_whitespace(cell.evidence),
            )
            for field_name, cell in values.items()
        }

        for arm_index in (1, 2):
            mean_field = f"Arm{arm_index}_Mean"
            sd_field = f"Arm{arm_index}_SD"
            total_field = f"Arm{arm_index}_Total"
            events_field = f"Arm{arm_index}_Events"

            normalized[total_field] = RobustJSONParser._normalize_numeric_cell(
                normalized.get(total_field, ExtractedCell()),
                allow_decimal=False,
            )
            normalized[events_field] = RobustJSONParser._normalize_numeric_cell(
                normalized.get(events_field, ExtractedCell()),
                allow_decimal=False,
            )

            mean_sd_pair = RobustJSONParser._extract_mean_sd_pair(
                normalized.get(mean_field, ExtractedCell()).value,
                normalized.get(mean_field, ExtractedCell()).evidence,
            )
            if mean_sd_pair is None:
                mean_sd_pair = RobustJSONParser._extract_mean_sd_pair(
                    normalized.get(sd_field, ExtractedCell()).value,
                    normalized.get(sd_field, ExtractedCell()).evidence,
                )

            if mean_sd_pair is not None:
                mean_value, sd_value = mean_sd_pair
                if mean_value and RobustJSONParser._cell_needs_backfill(normalized.get(mean_field, ExtractedCell())):
                    normalized[mean_field] = ExtractedCell(
                        value=mean_value,
                        evidence=normalized.get(mean_field, ExtractedCell()).evidence,
                    )
                else:
                    normalized[mean_field] = RobustJSONParser._normalize_numeric_cell(
                        normalized.get(mean_field, ExtractedCell()),
                        allow_decimal=True,
                    )
                if sd_value and RobustJSONParser._cell_needs_backfill(normalized.get(sd_field, ExtractedCell())):
                    normalized[sd_field] = ExtractedCell(
                        value=sd_value,
                        evidence=normalized.get(sd_field, ExtractedCell()).evidence,
                    )
                else:
                    normalized[sd_field] = RobustJSONParser._normalize_numeric_cell(
                        normalized.get(sd_field, ExtractedCell()),
                        allow_decimal=True,
                    )
            else:
                normalized[mean_field] = RobustJSONParser._normalize_numeric_cell(
                    normalized.get(mean_field, ExtractedCell()),
                    allow_decimal=True,
                )
                normalized[sd_field] = RobustJSONParser._normalize_numeric_cell(
                    normalized.get(sd_field, ExtractedCell()),
                    allow_decimal=True,
                )

            events_total_pair = RobustJSONParser._extract_events_total_pair(
                normalized.get(events_field, ExtractedCell()).value,
                normalized.get(events_field, ExtractedCell()).evidence,
            )
            if events_total_pair is None:
                events_total_pair = RobustJSONParser._extract_events_total_pair(
                    normalized.get(total_field, ExtractedCell()).value,
                    normalized.get(total_field, ExtractedCell()).evidence,
                )
            if events_total_pair is not None:
                events_value, total_value = events_total_pair
                current_events = normalized.get(events_field, ExtractedCell())
                current_total = normalized.get(total_field, ExtractedCell())
                if events_value and (
                    RobustJSONParser._cell_needs_backfill(current_events)
                    or "/" in RobustJSONParser._clean_whitespace(current_events.value)
                ):
                    normalized[events_field] = ExtractedCell(
                        value=events_value,
                        evidence=current_events.evidence,
                    )
                if total_value and (
                    RobustJSONParser._cell_needs_backfill(current_total)
                    or "/" in RobustJSONParser._clean_whitespace(current_total.value)
                ):
                    normalized[total_field] = ExtractedCell(
                        value=total_value,
                        evidence=current_total.evidence,
                    )

        return normalized

    @staticmethod
    def _normalize_stage4_field_value(
        value: Any,
        *,
        default_value: str,
        missing_reason: str,
    ) -> str:
        if missing_reason == "not_applicable" or default_value == "":
            return ""

        normalized = RobustJSONParser._normalize_cell_value(value, default_value)
        if missing_reason in {"not_reported", "unclear", "reported_graphically_only"} and normalized in {"", "Not Reported"}:
            return "Not Reported"
        if not normalized:
            return default_value
        if normalized.casefold() in {"not reported", "nr", "n/r", "not available", "not stated"}:
            return "Not Reported" if default_value != "" else ""
        return normalized

    @staticmethod
    def _normalize_numeric_cell(cell: ExtractedCell, *, allow_decimal: bool) -> ExtractedCell:
        value = RobustJSONParser._clean_whitespace(cell.value)
        evidence = RobustJSONParser._clean_whitespace(cell.evidence)
        if value == "":
            return ExtractedCell(value="", evidence=evidence)
        if value == "Not Reported":
            return ExtractedCell(value="Not Reported", evidence=evidence)
        if "/" in value:
            return ExtractedCell(value=value, evidence=evidence)
        if "%" in value and not allow_decimal:
            count_token = RobustJSONParser._extract_count_from_count_percent(value)
            if count_token:
                return ExtractedCell(value=count_token, evidence=evidence)
            return ExtractedCell(value=value, evidence=evidence)

        numeric_token = RobustJSONParser._extract_numeric_token(value, allow_decimal=allow_decimal)
        if numeric_token:
            return ExtractedCell(value=numeric_token, evidence=evidence)
        return ExtractedCell(value=value, evidence=evidence)

    @staticmethod
    def _extract_count_from_count_percent(text: str) -> str:
        normalized = RobustJSONParser._clean_whitespace(text)
        if not normalized or "%" not in normalized:
            return ""
        match = re.fullmatch(r"(\d[\d,]*)\s*\(\s*-?\d+(?:\.\d+)?\s*%?\s*\)\s*", normalized)
        if not match:
            return ""
        return RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=False)

    @staticmethod
    def _extract_mean_sd_pair(value: str, evidence: str) -> Optional[Tuple[str, str]]:
        for text in (RobustJSONParser._clean_whitespace(value), RobustJSONParser._clean_whitespace(evidence)):
            if not text:
                continue
            normalized = text.replace("\u00b1", "+/-")
            if "%" not in normalized:
                match = re.search(r"(-?\d+(?:\.\d+)?)\s*\(\s*(-?\d+(?:\.\d+)?)\s*\)", normalized)
                if match:
                    return (
                        RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=True),
                        RobustJSONParser._sanitize_numeric_token(match.group(2), allow_decimal=True),
                    )
            match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:\+/-)\s*(-?\d+(?:\.\d+)?)", normalized)
            if match:
                return (
                    RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=True),
                    RobustJSONParser._sanitize_numeric_token(match.group(2), allow_decimal=True),
                )

            match = re.search(
                r"mean\s*[=:]?\s*(-?\d+(?:\.\d+)?)\D+sd\s*[=:]?\s*(-?\d+(?:\.\d+)?)",
                normalized,
                re.IGNORECASE,
            )
            if match:
                return (
                    RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=True),
                    RobustJSONParser._sanitize_numeric_token(match.group(2), allow_decimal=True),
                )
        return None

    @staticmethod
    def _extract_events_total_pair(value: str, evidence: str) -> Optional[Tuple[str, str]]:
        for text in (RobustJSONParser._clean_whitespace(value), RobustJSONParser._clean_whitespace(evidence)):
            if not text:
                continue
            match = re.search(r"(\d[\d,]*)\s*/\s*(\d[\d,]*)", text)
            if match:
                return (
                    RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=False),
                    RobustJSONParser._sanitize_numeric_token(match.group(2), allow_decimal=False),
                )

            match = re.search(r"(\d[\d,]*)\s+(?:of|out of)\s+(\d[\d,]*)", text, re.IGNORECASE)
            if match:
                return (
                    RobustJSONParser._sanitize_numeric_token(match.group(1), allow_decimal=False),
                    RobustJSONParser._sanitize_numeric_token(match.group(2), allow_decimal=False),
                )
        return None

    @staticmethod
    def _cell_needs_backfill(cell: ExtractedCell) -> bool:
        return RobustJSONParser._clean_whitespace(cell.value) in {"", "Not Reported"}

    @staticmethod
    def _extract_numeric_token(text: str, *, allow_decimal: bool) -> str:
        match = re.search(r"-?\d[\d,]*(?:\.\d+)?", text)
        if not match:
            return ""
        return RobustJSONParser._sanitize_numeric_token(match.group(0), allow_decimal=allow_decimal)

    @staticmethod
    def _sanitize_numeric_token(token: str, *, allow_decimal: bool) -> str:
        cleaned = token.replace(",", "").strip()
        if not allow_decimal and re.fullmatch(r"-?\d+(?:\.0+)?", cleaned):
            return str(int(float(cleaned)))
        return cleaned

    @staticmethod
    def _build_field_metadata_fragment(
        *,
        field_name: str,
        missing_reason: str,
        confidence: str,
        evidence_location: str,
    ) -> str:
        details: List[str] = []
        if missing_reason and missing_reason != "reported":
            details.append(f"missing={missing_reason}")
        if confidence and confidence != "high":
            details.append(f"confidence={confidence}")
        if evidence_location:
            details.append(f"location={evidence_location}")
        if not details:
            return ""
        return f"{field_name}[{', '.join(details)}]"

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
    def _normalize_outcome_type(value: Any, *, statistic_description: Any = "") -> str:
        text = RobustJSONParser._normalize_text(value).lower()
        if text in {"continuous", "binary", "other"}:
            return text
        if text in {"dichotomous", "event"}:
            return "binary"
        statistic_text = RobustJSONParser._normalize_statistic_description(statistic_description).casefold()
        if any(token in statistic_text for token in {"mean", "median", "sd", "iqr"}):
            return "continuous"
        if any(token in statistic_text for token in {"event", "events", "count", "prevalence", "risk"}):
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
            "post_treatment": "endpoint",
            "post-treatment": "endpoint",
            "follow_up": "endpoint",
            "follow-up": "endpoint",
            "change": "change_from_baseline",
            "change_from_baseline": "change_from_baseline",
            "change score": "change_from_baseline",
            "mean_change": "change_from_baseline",
            "delta change": "change_from_baseline",
            "baseline_change": "change_from_baseline",
            "delta": "change_from_baseline",
            "other": "other",
        }
        return aliases.get(text, text)

    @staticmethod
    def _normalize_outcome_name(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value)
        if not text:
            return ""
        normalized = text.replace("\u2013", "-").replace("\u2014", "-")
        alias = OUTCOME_NAME_ALIASES.get(normalized.casefold())
        return alias or normalized

    @staticmethod
    def _normalize_timepoint(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value)
        if not text:
            return ""

        normalized = text.casefold()
        normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
        normalized = re.sub(r"^(at|after|following|follow-up at)\s+", "", normalized)
        if normalized in {"baseline", "pre-treatment", "pretreatment", "pre intervention", "before intervention"}:
            return "baseline"
        if normalized in {"endpoint", "final", "end of treatment", "follow-up"}:
            return "endpoint"

        match = re.search(
            r"(\d+(?:\.\d+)?)\s*[- ]?\s*(d|day|days|wk|wks|week|weeks|mo|mos|month|months|yr|yrs|year|years|hr|hrs|hour|hours)\b",
            normalized,
        )
        if match:
            quantity = match.group(1)
            unit = TIME_UNIT_ALIASES.get(match.group(2), match.group(2))
            suffix = unit if quantity == "1" else f"{unit}s"
            return f"{quantity} {suffix}"

        reverse_match = re.search(
            r"\b(day|days|week|weeks|month|months|year|years|hour|hours)\s*(\d+(?:\.\d+)?)\b",
            normalized,
        )
        if reverse_match:
            quantity = reverse_match.group(2)
            unit = TIME_UNIT_ALIASES.get(reverse_match.group(1), reverse_match.group(1))
            suffix = unit if quantity == "1" else f"{unit}s"
            return f"{quantity} {suffix}"

        return text

    @staticmethod
    def _normalize_statistic_description(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value)
        if not text:
            return ""
        normalized = text.replace("\u00b1", " +/- ").replace("卤", " +/- ")
        normalized = re.sub(r"[\(\)\[\]]", " ", normalized)
        normalized = re.sub(r"[;/]+", ", ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip(" ,")
        alias = STATISTIC_DESCRIPTION_ALIASES.get(normalized.casefold())
        if alias:
            return alias
        lowered = normalized.casefold()
        if "mean" in lowered and "sd" in lowered:
            return "mean, SD"
        if "event" in lowered and "total" in lowered:
            return "events, total"
        return normalized

    @staticmethod
    def _is_effect_only_row_candidate(candidate: RowCandidate) -> bool:
        outcome_name = RobustJSONParser._clean_whitespace(candidate.outcome_name)
        statistic_description = RobustJSONParser._clean_whitespace(candidate.statistic_description)
        note = RobustJSONParser._clean_whitespace(candidate.note)

        if outcome_name.casefold() in _EFFECT_ONLY_OUTCOME_NAMES:
            return True

        combined = " ".join(part for part in (outcome_name, statistic_description, note) if part)
        if not RobustJSONParser._looks_like_effect_measure(combined):
            return False
        if RobustJSONParser._has_raw_row_hints(combined):
            return False
        return True

    @staticmethod
    def _has_raw_row_hints(text: str) -> bool:
        normalized = (text or "").casefold()
        return any(
            token in normalized
            for token in (
                "mean",
                "sd",
                "standard deviation",
                "median",
                "iqr",
                "events",
                "event",
                "total",
                "count",
                "prevalence",
                "n=",
                "sample size",
            )
        )

    @staticmethod
    def _looks_like_effect_measure(text: str) -> bool:
        if not text:
            return False
        normalized = text.casefold()
        if any(
            phrase in normalized
            for phrase in (
                "risk ratio",
                "relative risk",
                "odds ratio",
                "hazard ratio",
                "rate ratio",
                "incidence rate ratio",
                "risk difference",
                "absolute risk reduction",
                "relative risk reduction",
                "number needed to treat",
                "number needed to harm",
                "mean difference",
                "standardized mean difference",
            )
        ):
            return True
        if re.search(r"\b(rrr|arr|nnt|nnh|smd|md)\b", normalized):
            return True
        if re.search(r"\brr\b", normalized):
            return True
        if re.search(r"\bOR\b", text):
            return True
        if re.search(r"\bHR\b", text):
            return True
        return False

    @staticmethod
    def _normalize_source_basis(value: Any) -> List[str]:
        if isinstance(value, list):
            items = value
        elif value is None:
            items = []
        else:
            items = [value]

        normalized_items: List[str] = []
        for item in items:
            text = RobustJSONParser._clean_whitespace(item).lower()
            if not text:
                continue
            if "table" in text:
                candidate = "table"
            elif "figure" in text or "graph" in text:
                candidate = "figure"
            else:
                candidate = "text"
            if candidate not in normalized_items:
                normalized_items.append(candidate)
        return normalized_items

    @staticmethod
    def _normalize_uncertainty(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value).lower()
        if text in {"low", "medium", "high"}:
            return text
        if text in {"uncertain", "possible", "ambiguous"}:
            return "high"
        if text in {"moderate", "medium confidence"}:
            return "medium"
        if text in {"low confidence"}:
            return "high"
        if text in {"high confidence", "certain"}:
            return "low"
        return ""

    @staticmethod
    def _normalize_missing_reason(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value).lower()
        aliases = {
            "reported": "reported",
            "not reported": "not_reported",
            "not_reported": "not_reported",
            "n/r": "not_reported",
            "nr": "not_reported",
            "not applicable": "not_applicable",
            "not_applicable": "not_applicable",
            "n/a": "not_applicable",
            "unclear": "unclear",
            "ambiguous": "unclear",
            "reported graphically only": "reported_graphically_only",
            "reported_graphically_only": "reported_graphically_only",
            "graphical_only": "reported_graphically_only",
        }
        return aliases.get(text, "")

    @staticmethod
    def _normalize_confidence(value: Any) -> str:
        text = RobustJSONParser._clean_whitespace(value).lower()
        if text in {"high", "medium", "low"}:
            return text
        if text == "moderate":
            return "medium"
        return ""

    @staticmethod
    def _normalize_study_unit_id(value: Any) -> str:
        return RobustJSONParser._clean_whitespace(value).upper()

    @staticmethod
    def _prefer_outcome_type(primary: str, secondary: str) -> str:
        if primary and primary != "other":
            return primary
        return secondary or primary or "other"

    @staticmethod
    def _prefer_value_type(primary: str, secondary: str) -> str:
        if primary and primary != "other":
            return primary
        return secondary or primary or "other"

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
        values = RobustJSONParser._normalize_row_value_cells(values)

        return ExtractionRow(
            row_id=candidate.row_id,
            study_unit_id=candidate.study_unit_id,
            outcome_name=candidate.outcome_name,
            outcome_type=outcome_type,
            timepoint=candidate.timepoint or RobustJSONParser._normalize_timepoint(extraction_row.timepoint),
            value_type=candidate.value_type or RobustJSONParser._normalize_value_type(extraction_row.value_type) or "other",
            outcome_unit=candidate.outcome_unit or RobustJSONParser._clean_whitespace(extraction_row.outcome_unit),
            statistic_description=candidate.statistic_description
            or RobustJSONParser._normalize_statistic_description(extraction_row.statistic_description),
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
