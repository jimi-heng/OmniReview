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


async def csv_writer(queue: asyncio.Queue, output_csv: Path, columns: List[str]) -> None:
    fieldnames = ["ID", "Title", "RelativePath"] + columns + ["Error"]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
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
    template_columns, _ = read_template_columns(template_path)
    preferred = ["ID", "Title", "RelativePath"] + [c for c in template_columns if c not in METADATA_FIELDS] + ["Error"]

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        csv_headers = list(reader.fieldnames or [])
        ordered_headers = [h for h in preferred if h in csv_headers]
        ordered_headers.extend([h for h in csv_headers if h not in ordered_headers])

        wb = Workbook()
        ws = wb.active
        ws.title = "baseline characteristics"
        ws.append(ordered_headers)
        for row in reader:
            ws.append([ILLEGAL_CHARACTERS_RE.sub("", row.get(col, "")) for col in ordered_headers])

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)


def state_to_final_rows(state: PipelineState) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    unit_by_id = {unit.unit_id: unit for unit in state.study_units}
    value_rows: List[Dict[str, str]] = []
    evidence_rows: List[Dict[str, str]] = []

    for extraction_row in state.extraction_rows:
        study_unit = unit_by_id.get(extraction_row.study_unit_id, StudyUnit(unit_id=extraction_row.study_unit_id))
        value_row = _build_base_metadata_row(state, study_unit)
        evidence_row: Dict[str, str] = {}

        _set_aliases(value_row, ["Outcome_Reproted"], "Yes")
        _set_aliases(value_row, ["Name_of_Outcome", "结局指标"], extraction_row.outcome_name)
        _set_aliases(value_row, ["Definition"], _display_value_type(extraction_row.value_type))
        _set_aliases(value_row, ["Measurement_Time_"], extraction_row.timepoint)
        _set_aliases(value_row, ["随访时间"], extraction_row.timepoint or state.profile.follow_up)
        _set_aliases(value_row, ["结局单位"], extraction_row.outcome_unit)
        _set_aliases(value_row, ["结局定义（终点值或变化值）"], _display_value_type_cn(extraction_row.value_type))
        _set_aliases(
            value_row,
            ["结局统计描述（均值标准差，或中位数95ci）"],
            extraction_row.statistic_description or _default_statistic_description(extraction_row.outcome_type),
        )

        _set_aliases(value_row, ["Arm1_Mean"], _cell_value(extraction_row, "Arm1_Mean"))
        _set_aliases(value_row, ["Arm1_SD"], _cell_value(extraction_row, "Arm1_SD"))
        _set_aliases(value_row, ["Arm1_Total"], _cell_value(extraction_row, "Arm1_Total"))
        _set_aliases(value_row, ["Arm2_Mean"], _cell_value(extraction_row, "Arm2_Mean"))
        _set_aliases(value_row, ["Arm2_SD"], _cell_value(extraction_row, "Arm2_SD"))
        _set_aliases(value_row, ["Arm2_Total"], _cell_value(extraction_row, "Arm2_Total"))
        _set_aliases(value_row, ["Arm1_Events"], _cell_value(extraction_row, "Arm1_Events"))
        _set_aliases(value_row, ["Arm2_Events"], _cell_value(extraction_row, "Arm2_Events"))

        _set_aliases(
            value_row,
            ["干预组数据结果(mean/median/events）"],
            _display_arm_primary(extraction_row, arm_index=1),
        )
        _set_aliases(
            value_row,
            ["干预组数据结果(SD/95%CI）"],
            _display_arm_secondary(extraction_row, arm_index=1),
        )
        _set_aliases(
            value_row,
            ["干预组数据样本量"],
            _cell_value(extraction_row, "Arm1_Total"),
        )
        _set_aliases(
            value_row,
            ["对照组数据结果(mean/median）"],
            _display_arm_primary(extraction_row, arm_index=2),
        )
        _set_aliases(
            value_row,
            ["对照组数据结果(SD/95%CI）"],
            _display_arm_secondary(extraction_row, arm_index=2),
        )
        _set_aliases(
            value_row,
            ["对照组数据样本量"],
            _cell_value(extraction_row, "Arm2_Total"),
        )

        note = extraction_row.note
        if extraction_row.error:
            note = f"{note} | Extraction error: {extraction_row.error}" if note else f"Extraction error: {extraction_row.error}"
        _set_aliases(value_row, ["Note", "note"], note)

        _set_aliases(evidence_row, ["Arm1_Mean"], _cell_evidence(extraction_row, "Arm1_Mean"))
        _set_aliases(evidence_row, ["Arm1_SD"], _cell_evidence(extraction_row, "Arm1_SD"))
        _set_aliases(evidence_row, ["Arm1_Total"], _cell_evidence(extraction_row, "Arm1_Total"))
        _set_aliases(evidence_row, ["Arm2_Mean"], _cell_evidence(extraction_row, "Arm2_Mean"))
        _set_aliases(evidence_row, ["Arm2_SD"], _cell_evidence(extraction_row, "Arm2_SD"))
        _set_aliases(evidence_row, ["Arm2_Total"], _cell_evidence(extraction_row, "Arm2_Total"))
        _set_aliases(evidence_row, ["Arm1_Events"], _cell_evidence(extraction_row, "Arm1_Events"))
        _set_aliases(evidence_row, ["Arm2_Events"], _cell_evidence(extraction_row, "Arm2_Events"))
        _set_aliases(evidence_row, ["Name_of_Outcome", "结局指标"], extraction_row.outcome_name)
        _set_aliases(evidence_row, ["Measurement_Time_", "随访时间"], extraction_row.timepoint)

        value_rows.append(value_row)
        evidence_rows.append(evidence_row)

    return value_rows, evidence_rows


def _build_base_metadata_row(state: PipelineState, study_unit: StudyUnit) -> Dict[str, str]:
    profile = state.profile
    row: Dict[str, str] = {}
    rayyan_id = _infer_rayyan_id(state.relative_path, state.title)
    study_identifier = _build_study_identifier(state, study_unit)

    _set_aliases(row, ["Year", "year"], profile.year)
    _set_aliases(row, ["Study_ID", "研究id"], study_identifier)
    _set_aliases(row, ["Study_Name"], profile.title or state.title)
    _set_aliases(row, ["title"], profile.title or state.title)
    _set_aliases(row, ["journal"], profile.journal)
    _set_aliases(row, ["authors"], profile.authors)
    _set_aliases(row, ["Country"], profile.country)
    _set_aliases(row, ["研究类型"], profile.study_design)
    _set_aliases(row, ["Trial_Number"], NOT_REPORTED)
    _set_aliases(row, ["Number_of_centers"], NOT_REPORTED)
    _set_aliases(row, ["Study_Inclusion"], study_unit.population_note or NOT_REPORTED)
    _set_aliases(row, ["Exclusion_Criteria"], NOT_REPORTED)
    _set_aliases(row, ["Diagnosis"], study_unit.population_note or NOT_REPORTED)
    _set_aliases(row, ["Sample_Size", "样本量"], profile.sample_size or NOT_REPORTED)
    _set_aliases(row, ["Age", "年龄，给出患者年龄的纳入标准，如果没有的话写基线资料的年龄"], NOT_REPORTED)
    _set_aliases(row, ["Gender"], NOT_REPORTED)
    _set_aliases(row, ["Follow_up"], profile.follow_up or NOT_REPORTED)

    arm1 = _arm_value(study_unit, 0)
    arm2 = _arm_value(study_unit, 1)
    _set_aliases(row, ["Arm_1_Specific_Regimens", "干预组措施"], arm1 or study_unit.intervention or NOT_REPORTED)
    _set_aliases(row, ["Arm1_Drugs", "干预组措施具体描述"], study_unit.intervention or arm1 or NOT_REPORTED)
    _set_aliases(row, ["Arm2_Specific_Regimens", "对照组措施"], arm2 or study_unit.comparison or NOT_REPORTED)
    _set_aliases(row, ["Arm2_Drugs", "对照组措施具体描述"], study_unit.comparison or arm2 or NOT_REPORTED)

    _set_aliases(row, ["key"], rayyan_id)
    _set_aliases(row, ["abstract"], "")
    _set_aliases(row, ["是否全文"], "是")
    return row


def _set_aliases(row: Dict[str, str], aliases: List[str], value: str) -> None:
    normalized = _normalize_output_value(value)
    for alias in aliases:
        row[alias] = normalized


def _normalize_output_value(value: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _cell_value(extraction_row: ExtractionRow, field_name: str) -> str:
    cell = extraction_row.values.get(field_name)
    if cell is None:
        return NOT_REPORTED
    return cell.value


def _cell_evidence(extraction_row: ExtractionRow, field_name: str) -> str:
    cell = extraction_row.values.get(field_name)
    if cell is None:
        return ""
    return cell.evidence


def _display_value_type(value_type: str) -> str:
    if value_type == "endpoint":
        return "endpoint"
    if value_type == "change_from_baseline":
        return "change_from_baseline"
    return value_type or NOT_REPORTED


def _display_value_type_cn(value_type: str) -> str:
    if value_type == "endpoint":
        return "终点值"
    if value_type == "change_from_baseline":
        return "变化值"
    return value_type or NOT_REPORTED


def _default_statistic_description(outcome_type: str) -> str:
    if outcome_type == "continuous":
        return "mean, SD"
    if outcome_type == "binary":
        return "events, total"
    return NOT_REPORTED


def _display_arm_primary(extraction_row: ExtractionRow, *, arm_index: int) -> str:
    if extraction_row.outcome_type == "binary":
        return _cell_value(extraction_row, f"Arm{arm_index}_Events")
    return _cell_value(extraction_row, f"Arm{arm_index}_Mean")


def _display_arm_secondary(extraction_row: ExtractionRow, *, arm_index: int) -> str:
    if extraction_row.outcome_type == "binary":
        return ""
    return _cell_value(extraction_row, f"Arm{arm_index}_SD")


def _build_study_identifier(state: PipelineState, study_unit: StudyUnit) -> str:
    base = state.profile.title or state.title or f"Paper {state.paper_id}"
    if len(state.study_units) <= 1:
        return base
    return f"{base} [{study_unit.unit_id}]"


def _arm_value(study_unit: StudyUnit, index: int) -> str:
    if index < len(study_unit.arms):
        return study_unit.arms[index]
    return ""


def _infer_rayyan_id(relative_path: str, fallback_title: str) -> str:
    match = re.search(r"(rayyan-\d+)", relative_path, flags=re.IGNORECASE)
    if match:
        return match.group(1)

    stem = Path(relative_path).stem
    if stem:
        return stem
    return fallback_title
