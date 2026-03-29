# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .models import NormalizedPICO


_KEY_PATTERN = re.compile(r"[^a-z0-9]+")

_COMPONENT_ALIASES: dict[str, tuple[str, ...]] = {
    "study_design": ("s", "study_design", "study_designs", "study_type", "study_types", "design", "study"),
    "population": ("p", "population", "participants", "participant", "patients", "patient", "subjects", "subject"),
    "intervention": (
        "i",
        "intervention",
        "interventions",
        "exposure",
        "exposures",
        "e",
        "indicator",
        "indicators",
    ),
    "comparison": (
        "c",
        "comparison",
        "comparisons",
        "comparator",
        "comparators",
        "control",
        "controls",
        "reference",
        "references",
        "ref",
        "r",
    ),
    "outcomes": ("o", "outcome", "outcomes", "endpoint", "endpoints"),
    "additional_criteria": (
        "es",
        "extra",
        "extras",
        "extra_rule",
        "extra_rules",
        "additional",
        "additional_criteria",
        "additional_rules",
        "criteria",
        "eligibility",
        "eligibility_criteria",
        "inclusion_criteria",
        "exclusion_criteria",
        "rules",
        "rule",
        "notes",
        "note",
        "remarks",
        "remark",
    ),
}

_EXPLANATORY_SUBKEYS = {
    "criteria",
    "condition",
    "conditions",
    "explanation",
    "explanations",
    "note",
    "notes",
    "remark",
    "remarks",
    "rule",
    "rules",
    "eligibility",
    "inclusion",
    "exclusion",
    "comment",
    "comments",
}

_DISPLAY_LABELS = {
    "study_design": "Study Design",
    "population": "Population",
    "intervention": "Intervention",
    "comparison": "Comparison",
    "outcomes": "Outcome",
    "additional_criteria": "Additional Criteria",
}


def normalize_key(value: Any) -> str:
    return _KEY_PATTERN.sub("_", str(value or "").strip().lower()).strip("_")


def coerce_pico_payload(pico_input: Any) -> dict[str, Any]:
    if pico_input is None:
        return {}
    if isinstance(pico_input, Mapping):
        return dict(pico_input.items())
    if isinstance(pico_input, Sequence) and not isinstance(pico_input, (str, bytes, bytearray)):
        if not pico_input:
            return {}
        first_item = pico_input[0]
        if isinstance(first_item, Mapping):
            return dict(first_item.items())
    raise TypeError("PICO payload must be a JSON object or a non-empty list of JSON objects")


def flatten_text(value: Any) -> str:
    text = _flatten_value(value)
    return text.strip()


def normalize_pico_input(pico_input: Any) -> NormalizedPICO:
    raw_fields = coerce_pico_payload(pico_input)
    normalized_fields = {normalize_key(key): value for key, value in raw_fields.items()}

    extra_rule_parts: list[str] = []
    study_design = _collect_component_text(normalized_fields, "study_design", extra_rule_parts)
    population = _collect_component_text(normalized_fields, "population", extra_rule_parts)
    intervention = _collect_component_text(normalized_fields, "intervention", extra_rule_parts)
    comparison = _collect_component_text(normalized_fields, "comparison", extra_rule_parts)
    outcomes = _collect_component_text(normalized_fields, "outcomes", extra_rule_parts)

    for alias in _COMPONENT_ALIASES["additional_criteria"]:
        if alias in normalized_fields:
            _append_unique(extra_rule_parts, _format_rule_text(alias, normalized_fields[alias]))

    return NormalizedPICO(
        study_design=study_design,
        population=population,
        intervention=intervention,
        comparison=comparison,
        outcomes=outcomes,
        additional_criteria="\n".join(extra_rule_parts).strip(),
        raw_fields=raw_fields,
        normalized_fields=normalized_fields,
    )


def _collect_component_text(
    normalized_fields: Mapping[str, Any],
    component_name: str,
    extra_rule_parts: list[str],
) -> str:
    parts: list[str] = []
    for alias in _COMPONENT_ALIASES[component_name]:
        if alias not in normalized_fields:
            continue
        text, side_rules = _flatten_component_value(normalized_fields[alias], _DISPLAY_LABELS[component_name])
        if text:
            _append_unique(parts, text)
        for rule in side_rules:
            _append_unique(extra_rule_parts, rule)
    return "\n".join(parts).strip()


def _flatten_component_value(value: Any, label: str) -> tuple[str, list[str]]:
    if value is None:
        return "", []
    if isinstance(value, str):
        return _clean_text(value), []
    if isinstance(value, Mapping):
        parts: list[str] = []
        side_rules: list[str] = []
        for raw_key, raw_item in value.items():
            key_text = str(raw_key).strip()
            normalized_key = normalize_key(raw_key)
            item_text = _flatten_value(raw_item)
            if not item_text:
                continue
            if normalized_key in _EXPLANATORY_SUBKEYS or normalized_key in _COMPONENT_ALIASES["additional_criteria"]:
                _append_unique(side_rules, _format_prefixed_rule(label, key_text or "Rule", item_text))
                continue
            if key_text:
                _append_unique(parts, f"{key_text}: {item_text}")
            else:
                _append_unique(parts, item_text)
        return "\n".join(parts).strip(), side_rules
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts: list[str] = []
        side_rules: list[str] = []
        for item in value:
            item_text, item_rules = _flatten_component_value(item, label)
            if item_text:
                _append_unique(parts, item_text)
            for rule in item_rules:
                _append_unique(side_rules, rule)
        return "\n".join(parts).strip(), side_rules
    return _clean_text(value), []


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            item_text = _flatten_value(item)
            key_text = str(key).strip()
            if not item_text:
                continue
            if key_text:
                parts.append(f"{key_text}: {item_text}")
            else:
                parts.append(item_text)
        return "\n".join(parts).strip()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [_flatten_value(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    return _clean_text(value)


def _format_rule_text(key: str, value: Any) -> str:
    text = _flatten_value(value)
    if not text:
        return ""
    label = "Additional Criteria" if key in _COMPONENT_ALIASES["additional_criteria"] else _DISPLAY_LABELS.get(key, _humanize_key(key))
    return f"{label}: {text}"


def _format_prefixed_rule(component_label: str, key: str, value_text: str) -> str:
    key_label = str(key).strip() or "Rule"
    return f"{component_label} {key_label}: {value_text}"


def _humanize_key(key: str) -> str:
    text = str(key).strip().replace("_", " ")
    return text[:1].upper() + text[1:] if text else ""


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).strip())


def _append_unique(parts: list[str], value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in parts:
        parts.append(cleaned)
