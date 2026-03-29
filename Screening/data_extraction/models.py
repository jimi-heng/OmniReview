# Author: Team 04
# This file is developed by our team

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class Paper:
    """Paper metadata for processing."""

    paper_id: int
    path: Path
    title: str


@dataclass
class ExtractionResult:
    """Result of extraction for a single paper."""

    paper_id: int
    title: str
    relative_path: str
    value_rows: List[Dict[str, str]] = field(default_factory=list)
    evidence_rows: List[Dict[str, str]] = field(default_factory=list)
    error: str = ""


@dataclass
class PaperProfile:
    """Paper-level metadata extracted during stage 1 profiling."""

    title: str = ""
    year: str = ""
    journal: str = ""
    authors: str = ""
    study_design: str = ""
    country: str = ""
    sample_size: str = ""
    follow_up: str = ""
    population_summary: str = ""
    inclusion_criteria: str = ""
    exclusion_criteria: str = ""
    age_info: str = ""
    gender_info: str = ""
    analysis_sample_size: str = ""
    randomized_sample_size: str = ""
    arm1_n: str = ""
    arm2_n: str = ""


@dataclass
class StudyUnit:
    """A single study unit or sub-study identified during stage 2."""

    unit_id: str = "SU-1"
    label: str = "Main Study"
    arms: List[str] = field(default_factory=lambda: ["", ""])
    population_note: str = ""
    intervention: str = ""
    comparison: str = ""
    population_summary: str = ""
    inclusion_criteria: str = ""
    exclusion_criteria: str = ""
    age_info: str = ""
    gender_info: str = ""
    analysis_sample_size: str = ""
    randomized_sample_size: str = ""
    arm1_n: str = ""
    arm2_n: str = ""


@dataclass
class ExtractedCell:
    """A single extracted value with its supporting evidence."""

    value: str = "Not Reported"
    evidence: str = ""


@dataclass
class RowCandidate:
    """Stage 3 inventory item representing one final extraction row."""

    row_id: str
    study_unit_id: str
    outcome_name: str
    outcome_type: str = "other"
    timepoint: str = ""
    value_type: str = ""
    outcome_unit: str = ""
    statistic_description: str = ""
    note: str = ""


@dataclass
class ExtractionRow:
    """Stage 4 extraction result for one row candidate."""

    row_id: str
    study_unit_id: str
    outcome_name: str
    outcome_type: str = "other"
    timepoint: str = ""
    value_type: str = ""
    outcome_unit: str = ""
    statistic_description: str = ""
    note: str = ""
    values: Dict[str, ExtractedCell] = field(default_factory=dict)
    error: str = ""


@dataclass
class ValidationIssue:
    """A single rule-based validation finding produced during stage 5."""

    severity: str = "warning"
    code: str = ""
    message: str = ""
    row_id: str = ""
    study_unit_id: str = ""
    field_name: str = ""


@dataclass
class ValidationReport:
    """Rule-based validation summary for the stage 1-4 pipeline output."""

    is_valid: bool = True
    total_row_candidates: int = 0
    total_extraction_rows: int = 0
    missing_row_count: int = 0
    duplicate_row_count: int = 0
    rows_with_extraction_errors: List[str] = field(default_factory=list)
    missing_row_ids: List[str] = field(default_factory=list)
    duplicate_row_signatures: List[str] = field(default_factory=list)
    empty_outcome_groups: List[str] = field(default_factory=list)
    field_not_reported_ratio: Dict[str, float] = field(default_factory=dict)
    error_type_counts: Dict[str, int] = field(default_factory=dict)
    recovery_attempt_count: int = 0
    recovery_success_count: int = 0
    recovery_attempted_row_ids: List[str] = field(default_factory=list)
    recovery_recovered_row_ids: List[str] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)

    def to_summary_dict(self) -> Dict[str, object]:
        """Return a stable, extensible summary payload for logs/evals."""
        return {
            "is_valid": self.is_valid,
            "total_row_candidates": self.total_row_candidates,
            "total_extraction_rows": self.total_extraction_rows,
            "missing_row_count": self.missing_row_count,
            "duplicate_row_count": self.duplicate_row_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "empty_outcome_groups": list(self.empty_outcome_groups),
            "field_not_reported_ratio": dict(self.field_not_reported_ratio),
            "error_type_counts": dict(self.error_type_counts),
            "recovery_attempt_count": self.recovery_attempt_count,
            "recovery_success_count": self.recovery_success_count,
            "recovery_attempted_row_ids": list(self.recovery_attempted_row_ids),
            "recovery_recovered_row_ids": list(self.recovery_recovered_row_ids),
            "issues": [asdict(issue) for issue in self.issues],
        }


@dataclass
class PipelineState:
    """Intermediate pipeline state for the multi-stage extraction flow."""

    paper_id: int
    title: str
    relative_path: str
    profile: PaperProfile = field(default_factory=PaperProfile)
    study_units: List[StudyUnit] = field(default_factory=list)
    row_candidates: List[RowCandidate] = field(default_factory=list)
    extraction_rows: List[ExtractionRow] = field(default_factory=list)
    validation_report: ValidationReport = field(default_factory=ValidationReport)
    stage_errors: Dict[str, str] = field(default_factory=dict)
    final_value_rows: List[Dict[str, str]] = field(default_factory=list)
    final_evidence_rows: List[Dict[str, str]] = field(default_factory=list)
    legacy_result: ExtractionResult | None = None
