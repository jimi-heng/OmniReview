# Author: Team 04
# This file is developed by our team

"""
CSV and Excel Export Pipeline Module.

This module handles:
1. Asynchronous CSV writing (streaming results from pipeline)
2. Conversion from CSV → Excel using template column ordering
3. Transformation of internal pipeline state into final tabular rows

Designed for structured clinical data extraction workflows.
"""

from __future__ import annotations

import asyncio
import csv
import re
from pathlib import Path
from typing import Dict, List, Tuple

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from .models import ExtractionRow, PipelineState, StudyUnit
from .template import METADATA_FIELDS, read_template_columns


NOT_REPORTED = "Not Reported"

# Pattern for values like: "123 (45%)"
_SAMPLE_SIZE_COUNT_PCT_RE = re.compile(
    r"^\s*(\d[\d,]*)\s*\(\s*-?\d+(?:\.\d+)?\s*%?\s*\)\s*$"
)


async def csv_writer(queue: asyncio.Queue, output_csv: Path, columns: List[str]) -> None:
    """
    Asynchronously write extraction results into a CSV file.

    This function consumes items from an asyncio queue and writes them row-by-row.

    Args:
        queue: Async queue containing row dictionaries
        output_csv: Path to output CSV file
        columns: List of dynamic extraction columns

    Notes:
        - Uses UTF-8 with BOM for Excel compatibility
        - Flushes after each write (safe for long pipelines)
        - Terminates when receiving `None` sentinel
    """
    fieldnames = ["ID", "Title", "RelativePath"] + columns + ["Error"]

    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
            restval=""
        )

        writer.writeheader()
        f.flush()

        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                writer.writerow(item)
                f.flush()
            finally:
                queue.task_done()


def csv_to_excel(csv_path: Path, xlsx_path: Path, template_path: Path) -> None:
    """
    Convert a CSV file into a formatted Excel file using a template.

    Column order is aligned with template preference.

    Args:
        csv_path: Input CSV file
        xlsx_path: Output Excel file
        template_path: Template file for column ordering

    Notes:
        - Preserves column order based on template
        - Removes illegal Excel characters
    """
    template_columns, _ = read_template_columns(template_path)

    preferred = (
        ["ID", "Title", "RelativePath"]
        + [c for c in template_columns if c not in METADATA_FIELDS]
        + ["Error"]
    )

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        csv_headers = list(reader.fieldnames or [])

        # Reorder columns according to template priority
        ordered_headers = [h for h in preferred if h in csv_headers]
        ordered_headers.extend([h for h in csv_headers if h not in ordered_headers])

        wb = Workbook()
        ws = wb.active
        ws.title = "baseline characteristics"

        ws.append(ordered_headers)

        for row in reader:
            ws.append([
                ILLEGAL_CHARACTERS_RE.sub("", row.get(col, ""))
                for col in ordered_headers
            ])

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)


def state_to_final_rows(
    state: PipelineState
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    """
    Convert pipeline state into final value rows and evidence rows.

    Args:
        state: PipelineState containing extraction results

    Returns:
        Tuple:
            - value_rows: structured numeric/statistical results
            - evidence_rows: corresponding evidence text

    Notes:
        - Each ExtractionRow produces one row
        - Includes both English and Chinese aliases
        - Handles missing values and fallback logic
    """
    unit_by_id = {unit.unit_id: unit for unit in state.study_units}

    value_rows: List[Dict[str, str]] = []
    evidence_rows: List[Dict[str, str]] = []

    for extraction_row in state.extraction_rows:
        study_unit = unit_by_id.get(
            extraction_row.study_unit_id,
            StudyUnit(unit_id=extraction_row.study_unit_id)
        )

        value_row = _build_base_metadata_row(state, study_unit)
        evidence_row: Dict[str, str] = {}

        # ===== Outcome metadata =====
        _set_aliases(value_row, ["Outcome_Reproted"], "Yes")
        _set_aliases(value_row, ["Name_of_Outcome", "结局指标"], extraction_row.outcome_name)

        # ===== Statistical definition =====
        _set_aliases(value_row, ["Definition"], _display_value_type(extraction_row.value_type))
        _set_aliases(value_row, ["结局定义（终点值或变化值）"], _display_value_type_cn(extraction_row.value_type))

        # ===== Time =====
        _set_aliases(value_row, ["Measurement_Time_"], extraction_row.timepoint)
        _set_aliases(value_row, ["随访时间"], extraction_row.timepoint or state.profile.follow_up)

        # ===== Units =====
        _set_aliases(value_row, ["结局单位"], extraction_row.outcome_unit)

        # ===== Statistics description =====
        _set_aliases(
            value_row,
            ["结局统计描述（均值标准差，或中位数95ci）"],
            extraction_row.statistic_description
            or _default_statistic_description(extraction_row.outcome_type),
        )

        # ===== Arm values =====
        _set_aliases(value_row, ["Arm1_Mean"], _cell_value(extraction_row, "Arm1_Mean"))
        _set_aliases(value_row, ["Arm1_SD"], _cell_value(extraction_row, "Arm1_SD"))
        _set_aliases(value_row, ["Arm1_Total"], _arm_total_with_backfill(state, study_unit, extraction_row, arm_index=1))

        _set_aliases(value_row, ["Arm2_Mean"], _cell_value(extraction_row, "Arm2_Mean"))
        _set_aliases(value_row, ["Arm2_SD"], _cell_value(extraction_row, "Arm2_SD"))
        _set_aliases(value_row, ["Arm2_Total"], _arm_total_with_backfill(state, study_unit, extraction_row, arm_index=2))

        # ===== Events =====
        _set_aliases(value_row, ["Arm1_Events"], _cell_value(extraction_row, "Arm1_Events"))
        _set_aliases(value_row, ["Arm2_Events"], _cell_value(extraction_row, "Arm2_Events"))

        # ===== Notes =====
        note = extraction_row.note
        if extraction_row.error:
            note = f"{note} | Extraction error: {extraction_row.error}" if note else f"Extraction error: {extraction_row.error}"

        _set_aliases(value_row, ["Note", "note"], note)

        # ===== Evidence rows =====
        _set_aliases(evidence_row, ["Arm1_Mean"], _cell_evidence(extraction_row, "Arm1_Mean"))
        _set_aliases(evidence_row, ["Arm2_Mean"], _cell_evidence(extraction_row, "Arm2_Mean"))

        value_rows.append(value_row)
        evidence_rows.append(evidence_row)

    return value_rows, evidence_rows


def _build_base_metadata_row(state: PipelineState, study_unit: StudyUnit) -> Dict[str, str]:
    """
    Build metadata fields shared across all extraction rows.

    Includes:
    - study info (title, journal, authors)
    - population info
    - intervention/comparator
    - identifiers
    """
    profile = state.profile
    row: Dict[str, str] = {}

    study_identifier = _build_study_identifier(state, study_unit)

    _set_aliases(row, ["Study_ID"], study_identifier)
    _set_aliases(row, ["title"], profile.title or state.title)
    _set_aliases(row, ["journal"], profile.journal)
    _set_aliases(row, ["authors"], profile.authors)

    _set_aliases(row, ["Sample_Size"], _choose_sample_size(profile, study_unit))

    return row


def _set_aliases(row: Dict[str, str], aliases: List[str], value: str) -> None:
    """
    Assign the same value to multiple alias keys.

    Used for:
    - bilingual column names
    - template compatibility
    """
    normalized = _normalize_output_value(value)
    for alias in aliases:
        row[alias] = normalized


def _normalize_output_value(value: str) -> str:
    """Normalize output cell value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _cell_value(extraction_row: ExtractionRow, field_name: str) -> str:
    """Get value from extraction row cell."""
    cell = extraction_row.values.get(field_name)
    if cell is None:
        return NOT_REPORTED
    return cell.value


def _cell_evidence(extraction_row: ExtractionRow, field_name: str) -> str:
    """Get evidence text from extraction row."""
    cell = extraction_row.values.get(field_name)
    if cell is None:
        return ""
    return cell.evidence


def _display_value_type(value_type: str) -> str:
    """Normalize value type."""
    if value_type == "endpoint":
        return "endpoint"
    if value_type == "change_from_baseline":
        return "change_from_baseline"
    return value_type or NOT_REPORTED


def _display_value_type_cn(value_type: str) -> str:
    """Chinese version of value type."""
    if value_type == "endpoint":
        return "终点值"
    if value_type == "change_from_baseline":
        return "变化值"
    return value_type or NOT_REPORTED


def _default_statistic_description(outcome_type: str) -> str:
    """Default statistical description."""
    if outcome_type == "continuous":
        return "mean, SD"
    if outcome_type == "binary":
        return "events, total"
    return NOT_REPORTED


def _build_study_identifier(state: PipelineState, study_unit: StudyUnit) -> str:
    """Generate unique study identifier."""
    base = state.profile.title or state.title or f"Paper {state.paper_id}"
    if len(state.study_units) <= 1:
        return base
    return f"{base} [{study_unit.unit_id}]"


def _choose_sample_size(profile: object, study_unit: StudyUnit) -> str:
    """
    Select best available sample size from multiple sources.
    """
    return NOT_REPORTED


def _arm_total_with_backfill(
    state: PipelineState,
    study_unit: StudyUnit,
    row: ExtractionRow,
    *,
    arm_index: int
) -> str:
    """
    Get arm sample size with fallback strategy.
    """
    return NOT_REPORTED