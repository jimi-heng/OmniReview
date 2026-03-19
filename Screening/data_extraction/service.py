from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from .http_client import LLMClient
from .models import (
    ExtractedCell,
    ExtractionResult,
    ExtractionRow,
    Paper,
    PaperProfile,
    PipelineState,
    RowCandidate,
    StudyUnit,
    ValidationIssue,
    ValidationReport,
)
from .output import state_to_final_rows
from .parsing import BINARY_ONLY_FIELDS, CANONICAL_VALUE_FIELDS, CONTINUOUS_ONLY_FIELDS, RobustJSONParser
from .pdf import load_pdf_bytes
from .prompts import (
    generate_columns_section,
    generate_user_prompt,
    get_default_pico,
    get_stage1_prompt,
    get_stage2_prompt,
    get_stage3_prompt,
    get_stage4_prompt,
    get_system_prompt,
)

logger = logging.getLogger(__name__)


def _relative_path(path: Path, project_dir: Path) -> str:
    try:
        return str(path.relative_to(project_dir))
    except Exception:
        return str(path)


class ResponseParser(Protocol):
    def parse(self, text: str, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]: ...


@dataclass(frozen=True)
class ExtractionRequest:
    llm_columns: List[str]
    pages_spec: Optional[List[int]]
    project_type: str
    pico_dict: Optional[Dict[str, str]]
    pipeline_mode: str = "legacy"


class EnhancedDataExtractor:
    """Orchestrates PDF->prompt->LLM->parse for the legacy single-shot extraction flow."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        parser: ResponseParser = RobustJSONParser,
        project_dir: Path,
        debug_prompt: bool = False,
    ) -> None:
        self._llm = llm_client
        self._parser = parser
        self._project_dir = project_dir
        self._debug_prompt = debug_prompt

    async def extract(self, *, paper: Paper, request: ExtractionRequest) -> ExtractionResult:
        base_error = ""
        value_rows: List[Dict[str, str]] = []
        evidence_rows: List[Dict[str, str]] = []

        pico_dict = request.pico_dict or get_default_pico(request.project_type)

        try:
            pdf_bytes = load_pdf_bytes(paper.path, request.pages_spec)

            columns_section = generate_columns_section(request.llm_columns)
            system_prompt = get_system_prompt(request.project_type)
            user_prompt = generate_user_prompt(
                project_type=request.project_type,
                pico_dict=pico_dict,
                columns_section=columns_section,
                paper_id=paper.paper_id,
            )
            full_prompt = system_prompt + "\n\n" + user_prompt

            if self._debug_prompt:
                logger.debug("Legacy prompt (first 500 chars) for paper_id=%s: %s", paper.paper_id, full_prompt[:500])

            raw_text = await self._llm.extract_text(pdf_bytes=pdf_bytes, filename=paper.path.name, prompt=full_prompt)
            value_rows, evidence_rows = self._parser.parse(raw_text, request.llm_columns)
        except Exception as exc:
            base_error = str(exc)
            logger.exception("Legacy extraction failed for paper_id=%s", paper.paper_id)
            traceback.print_exc()

        return ExtractionResult(
            paper_id=paper.paper_id,
            title=paper.title,
            relative_path=_relative_path(paper.path, self._project_dir),
            value_rows=value_rows,
            evidence_rows=evidence_rows,
            error=base_error,
        )


class PipelineOrchestrator:
    """Phase-aware data extraction pipeline with legacy/phase1/phase2 execution modes."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        project_dir: Path,
        debug_prompt: bool = False,
        parser: type[RobustJSONParser] = RobustJSONParser,
        fallback_extractor: EnhancedDataExtractor | None = None,
    ) -> None:
        self._llm = llm_client
        self._project_dir = project_dir
        self._debug_prompt = debug_prompt
        self._parser = parser
        self._fallback = fallback_extractor or EnhancedDataExtractor(
            llm_client=llm_client,
            parser=parser,
            project_dir=project_dir,
            debug_prompt=debug_prompt,
        )

    async def run(self, *, paper: Paper, request: ExtractionRequest) -> PipelineState:
        mode = self._normalize_mode(request.pipeline_mode)
        state = PipelineState(
            paper_id=paper.paper_id,
            title=paper.title,
            relative_path=_relative_path(paper.path, self._project_dir),
        )

        if mode == "legacy":
            state.legacy_result = await self._fallback.extract(paper=paper, request=request)
            if state.legacy_result.error:
                state.stage_errors["legacy"] = state.legacy_result.error
            return state

        pico_dict = request.pico_dict or get_default_pico(request.project_type)
        pdf_bytes: bytes | None = None

        try:
            pdf_bytes = load_pdf_bytes(paper.path, request.pages_spec)
        except Exception as exc:
            self._record_stage_error(state, "stage1", exc)
            state.stage_errors.setdefault("stage2", "Skipped because PDF bytes could not be loaded.")
            state.study_units = [self._default_study_unit()]

        if pdf_bytes is not None:
            try:
                state.profile = await self._run_stage1(
                    paper=paper,
                    pdf_bytes=pdf_bytes,
                    project_type=request.project_type,
                )
            except Exception as exc:
                self._record_stage_error(state, "stage1", exc)

            try:
                state.study_units = await self._run_stage2(
                    paper=paper,
                    pdf_bytes=pdf_bytes,
                    project_type=request.project_type,
                    pico_dict=pico_dict,
                    profile=state.profile,
                )
            except Exception as exc:
                self._record_stage_error(state, "stage2", exc)
                state.study_units = [self._default_study_unit()]

        if not state.study_units:
            state.study_units = [self._default_study_unit()]

        if mode == "phase1":
            state.legacy_result = await self._fallback.extract(paper=paper, request=request)
            if state.legacy_result.error:
                state.stage_errors.setdefault("legacy_fallback", state.legacy_result.error)
            return state

        if pdf_bytes is None:
            state.legacy_result = await self._fallback.extract(paper=paper, request=request)
            if state.legacy_result.error:
                state.stage_errors.setdefault("legacy_fallback", state.legacy_result.error)
            return state

        try:
            state.row_candidates = await self._run_stage3(
                paper=paper,
                pdf_bytes=pdf_bytes,
                project_type=request.project_type,
                pico_dict=pico_dict,
                profile=state.profile,
                study_units=state.study_units,
            )
        except Exception as exc:
            self._record_stage_error(state, "stage3", exc)
            state.legacy_result = await self._fallback.extract(paper=paper, request=request)
            if state.legacy_result.error:
                state.stage_errors.setdefault("legacy_fallback", state.legacy_result.error)
            return state

        state.extraction_rows = await self._run_stage4(
            state=state,
            paper=paper,
            pdf_bytes=pdf_bytes,
            project_type=request.project_type,
            study_units=state.study_units,
            row_candidates=state.row_candidates,
            profile=state.profile,
        )
        try:
            self.validate_state(state)
        except Exception as exc:
            self._record_stage_error(state, "stage5", exc)

        state.final_value_rows, state.final_evidence_rows = state_to_final_rows(state)
        if not state.final_value_rows:
            state.legacy_result = await self._fallback.extract(paper=paper, request=request)
            if state.legacy_result.error:
                state.stage_errors.setdefault("legacy_fallback", state.legacy_result.error)
        return state

    async def extract(self, *, paper: Paper, request: ExtractionRequest) -> ExtractionResult:
        state = await self.run(paper=paper, request=request)
        mode = self._normalize_mode(request.pipeline_mode)

        if mode == "legacy" or mode == "phase1":
            if state.legacy_result is not None:
                return state.legacy_result
            return ExtractionResult(
                paper_id=paper.paper_id,
                title=paper.title,
                relative_path=state.relative_path,
                error="Legacy extraction did not produce a result.",
            )

        if state.final_value_rows:
            return ExtractionResult(
                paper_id=paper.paper_id,
                title=paper.title,
                relative_path=state.relative_path,
                value_rows=state.final_value_rows,
                evidence_rows=state.final_evidence_rows,
                error="",
            )

        if state.legacy_result is not None:
            return state.legacy_result

        return ExtractionResult(
            paper_id=paper.paper_id,
            title=paper.title,
            relative_path=state.relative_path,
            error="Phase 2 extraction did not produce any rows.",
        )

    async def build_row_inventory(self, *, paper: Paper, request: ExtractionRequest) -> PipelineState:
        state = PipelineState(
            paper_id=paper.paper_id,
            title=paper.title,
            relative_path=_relative_path(paper.path, self._project_dir),
        )
        pico_dict = request.pico_dict or get_default_pico(request.project_type)

        try:
            pdf_bytes = load_pdf_bytes(paper.path, request.pages_spec)
        except Exception as exc:
            self._record_stage_error(state, "stage1", exc)
            state.stage_errors.setdefault("stage2", "Skipped because PDF bytes could not be loaded.")
            state.stage_errors.setdefault("stage3", "Skipped because PDF bytes could not be loaded.")
            state.study_units = [self._default_study_unit()]
            return state

        try:
            state.profile = await self._run_stage1(
                paper=paper,
                pdf_bytes=pdf_bytes,
                project_type=request.project_type,
            )
        except Exception as exc:
            self._record_stage_error(state, "stage1", exc)

        try:
            state.study_units = await self._run_stage2(
                paper=paper,
                pdf_bytes=pdf_bytes,
                project_type=request.project_type,
                pico_dict=pico_dict,
                profile=state.profile,
            )
        except Exception as exc:
            self._record_stage_error(state, "stage2", exc)
            state.study_units = [self._default_study_unit()]

        if not state.study_units:
            state.study_units = [self._default_study_unit()]

        try:
            state.row_candidates = await self._run_stage3(
                paper=paper,
                pdf_bytes=pdf_bytes,
                project_type=request.project_type,
                pico_dict=pico_dict,
                profile=state.profile,
                study_units=state.study_units,
            )
        except Exception as exc:
            self._record_stage_error(state, "stage3", exc)

        return state

    async def build_extraction_rows(self, *, paper: Paper, request: ExtractionRequest) -> PipelineState:
        state = await self.build_row_inventory(paper=paper, request=request)
        if state.stage_errors.get("stage3") or not state.row_candidates:
            return state

        try:
            pdf_bytes = load_pdf_bytes(paper.path, request.pages_spec)
        except Exception as exc:
            self._record_stage_error(state, "stage4", exc)
            return state

        state.extraction_rows = await self._run_stage4(
            state=state,
            paper=paper,
            pdf_bytes=pdf_bytes,
            project_type=request.project_type,
            study_units=state.study_units,
            row_candidates=state.row_candidates,
            profile=state.profile,
        )
        try:
            self.validate_state(state)
        except Exception as exc:
            self._record_stage_error(state, "stage5", exc)
        state.final_value_rows, state.final_evidence_rows = state_to_final_rows(state)
        return state

    def validate_state(self, state: PipelineState) -> ValidationReport:
        report = self._run_stage5(state=state)
        state.validation_report = report
        return report

    async def _run_stage1(self, *, paper: Paper, pdf_bytes: bytes, project_type: str) -> PaperProfile:
        raw_text = await self._call_stage(
            stage_name="stage1",
            pdf_bytes=pdf_bytes,
            filename=paper.path.name,
            prompt=get_stage1_prompt(project_type=project_type, paper_id=paper.paper_id),
        )
        payload = self._parser.parse_json_payload(raw_text)
        if not isinstance(payload, dict):
            raise ValueError("Stage 1 must return a single JSON object.")

        return PaperProfile(
            title=self._string(payload.get("title")),
            year=self._string(payload.get("year")),
            journal=self._string(payload.get("journal")),
            authors=self._string(payload.get("authors")),
            study_design=self._string(payload.get("study_design")),
            country=self._string(payload.get("country")),
            sample_size=self._string(payload.get("sample_size")),
            follow_up=self._string(payload.get("follow_up")),
        )

    async def _run_stage2(
        self,
        *,
        paper: Paper,
        pdf_bytes: bytes,
        project_type: str,
        pico_dict: Dict[str, str],
        profile: PaperProfile,
    ) -> List[StudyUnit]:
        raw_text = await self._call_stage(
            stage_name="stage2",
            pdf_bytes=pdf_bytes,
            filename=paper.path.name,
            prompt=get_stage2_prompt(
                project_type=project_type,
                pico_dict=pico_dict,
                paper_id=paper.paper_id,
                paper_profile=self._paper_profile_as_dict(profile),
            ),
        )
        payload = self._parser.parse_json_payload(raw_text)
        if not isinstance(payload, list):
            raise ValueError("Stage 2 must return a JSON array.")

        study_units = [
            self._build_study_unit(item, index)
            for index, item in enumerate(payload, start=1)
            if isinstance(item, dict)
        ]
        if not study_units:
            raise ValueError("Stage 2 returned no valid study units.")
        return study_units

    async def _run_stage3(
        self,
        *,
        paper: Paper,
        pdf_bytes: bytes,
        project_type: str,
        pico_dict: Dict[str, str],
        profile: PaperProfile,
        study_units: List[StudyUnit],
    ) -> List[RowCandidate]:
        raw_text = await self._call_stage(
            stage_name="stage3",
            pdf_bytes=pdf_bytes,
            filename=paper.path.name,
            prompt=get_stage3_prompt(
                project_type=project_type,
                pico_dict=pico_dict,
                paper_id=paper.paper_id,
                paper_profile=self._paper_profile_as_dict(profile),
                study_units=[self._study_unit_as_dict(study_unit) for study_unit in study_units],
            ),
        )
        candidates = self._parser.parse_row_candidates(raw_text)
        return self._parser.normalize_row_candidates(
            candidates,
            valid_study_unit_ids=[study_unit.unit_id for study_unit in study_units],
        )

    async def _run_stage4(
        self,
        *,
        state: PipelineState,
        paper: Paper,
        pdf_bytes: bytes,
        project_type: str,
        study_units: List[StudyUnit],
        row_candidates: List[RowCandidate],
        profile: PaperProfile,
    ) -> List[ExtractionRow]:
        study_unit_by_id = {study_unit.unit_id: study_unit for study_unit in study_units}
        grouped_candidates: Dict[Tuple[str, str], List[RowCandidate]] = defaultdict(list)
        for candidate in row_candidates:
            group_key = (candidate.study_unit_id, candidate.outcome_name.strip().casefold())
            grouped_candidates[group_key].append(candidate)

        extraction_rows: List[ExtractionRow] = []
        for (study_unit_id, outcome_name_key), candidates in grouped_candidates.items():
            study_unit = study_unit_by_id.get(study_unit_id, self._default_study_unit())
            try:
                raw_text = await self._call_stage(
                    stage_name=f"stage4:{study_unit_id}:{outcome_name_key}",
                    pdf_bytes=pdf_bytes,
                    filename=paper.path.name,
                    prompt=get_stage4_prompt(
                        project_type=project_type,
                        paper_id=paper.paper_id,
                        paper_profile=self._paper_profile_as_dict(profile),
                        study_unit=self._study_unit_as_dict(study_unit),
                        row_candidates=[self._row_candidate_as_dict(candidate) for candidate in candidates],
                    ),
                )
                parsed_rows = self._parser.parse_extraction_rows(raw_text, candidates)
                extraction_rows.extend(self._parser.normalize_extraction_rows(parsed_rows, candidates))
            except Exception as exc:
                stage_key = f"stage4:{study_unit_id}:{outcome_name_key}"
                self._record_stage_error(state, stage_key, exc)
                for candidate in candidates:
                    extraction_rows.append(self._blank_extraction_row(candidate, error=str(exc)))
        return extraction_rows

    async def _call_stage(self, *, stage_name: str, pdf_bytes: bytes, filename: str, prompt: str) -> str:
        if self._debug_prompt:
            logger.debug("%s prompt (first 500 chars) for %s: %s", stage_name, filename, prompt[:500])
        return await self._llm.extract_text(pdf_bytes=pdf_bytes, filename=filename, prompt=prompt)

    def _run_stage5(self, *, state: PipelineState) -> ValidationReport:
        report = ValidationReport(
            total_row_candidates=len(state.row_candidates),
            total_extraction_rows=len(state.extraction_rows),
        )
        candidate_by_id = {candidate.row_id: candidate for candidate in state.row_candidates}
        known_unit_ids = {study_unit.unit_id for study_unit in state.study_units}
        applicable_counts: Dict[str, int] = defaultdict(int)
        not_reported_counts: Dict[str, int] = defaultdict(int)
        row_ids_seen: Dict[str, List[str]] = defaultdict(list)
        signature_to_row_ids: Dict[Tuple[str, str, str, str], List[str]] = defaultdict(list)
        reported_groups: set[Tuple[str, str]] = set()

        filtered_rows: List[ExtractionRow] = []
        for row in state.extraction_rows:
            if candidate_by_id and row.row_id not in candidate_by_id:
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="unexpected_row_id",
                    message=f"Row {row.row_id} is not present in the Stage 3 inventory and was ignored.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )
                continue
            filtered_rows.append(row)
        state.extraction_rows = filtered_rows

        if candidate_by_id:
            present_row_ids = {row.row_id for row in state.extraction_rows}
            missing_candidates = [candidate for candidate in state.row_candidates if candidate.row_id not in present_row_ids]
            report.missing_row_ids = [candidate.row_id for candidate in missing_candidates]
            report.missing_row_count = len(missing_candidates)
            for candidate in missing_candidates:
                state.extraction_rows.append(
                    self._blank_extraction_row(candidate, error="Missing before Stage 5 validation.")
                )
                self._add_validation_issue(
                    report,
                    severity="error",
                    code="missing_row",
                    message=f"Row {candidate.row_id} was missing after Stage 4 and was backfilled as Not Reported.",
                    row_id=candidate.row_id,
                    study_unit_id=candidate.study_unit_id,
                )

            order = {candidate.row_id: index for index, candidate in enumerate(state.row_candidates)}
            state.extraction_rows.sort(key=lambda row: (order.get(row.row_id, len(order)), row.row_id))

        report.total_extraction_rows = len(state.extraction_rows)

        for row in state.extraction_rows:
            self._normalize_row_for_validation(row)

            row_ids_seen[row.row_id].append(row.row_id)
            signature = self._row_signature(row)
            signature_to_row_ids[signature].append(row.row_id)

            if known_unit_ids and row.study_unit_id not in known_unit_ids:
                self._add_validation_issue(
                    report,
                    severity="error",
                    code="unknown_study_unit",
                    message=f"Row {row.row_id} references unknown study unit {row.study_unit_id}.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )

            if row.error:
                report.rows_with_extraction_errors.append(row.row_id)
                self._add_validation_issue(
                    report,
                    severity="error",
                    code="stage4_row_error",
                    message=f"Row {row.row_id} has extraction error: {row.error}",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )

            applicable_fields = self._applicable_value_fields(row.outcome_type)
            missing_fields: List[str] = []
            for field_name in applicable_fields:
                applicable_counts[field_name] += 1
                if row.values[field_name].value == "Not Reported":
                    not_reported_counts[field_name] += 1
                    missing_fields.append(field_name)

            if self._row_has_reported_value(row):
                reported_groups.add((row.study_unit_id, row.outcome_name.casefold()))

            if row.outcome_type in {"continuous", "binary"} and missing_fields:
                severity = "warning"
                code = "row_all_applicable_missing" if len(missing_fields) == len(applicable_fields) else "row_partial_missing"
                detail = ", ".join(missing_fields)
                self._add_validation_issue(
                    report,
                    severity=severity,
                    code=code,
                    message=f"Row {row.row_id} is missing applicable fields: {detail}.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )

            if row.outcome_type == "other" and not self._row_has_reported_value(row) and not row.note:
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="other_outcome_without_note",
                    message=f"Row {row.row_id} has outcome_type=other but no extracted value or explanatory note.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )

        for row_id, seen in row_ids_seen.items():
            if len(seen) > 1:
                self._add_validation_issue(
                    report,
                    severity="error",
                    code="duplicate_row_id",
                    message=f"Row ID {row_id} appears {len(seen)} times after Stage 4.",
                    row_id=row_id,
                )

        for signature, row_ids in signature_to_row_ids.items():
            if len(row_ids) > 1:
                signature_text = self._format_row_signature(signature)
                report.duplicate_row_signatures.append(signature_text)
                self._add_validation_issue(
                    report,
                    severity="error",
                    code="duplicate_row_signature",
                    message=f"Duplicate extraction rows found for {signature_text}.",
                    row_id=",".join(row_ids),
                )

        candidate_groups = {(candidate.study_unit_id, candidate.outcome_name.casefold()) for candidate in state.row_candidates}
        for study_unit_id, outcome_name_key in sorted(candidate_groups):
            if (study_unit_id, outcome_name_key) not in reported_groups:
                group_label = f"{study_unit_id}:{outcome_name_key}"
                report.empty_outcome_groups.append(group_label)
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="outcome_group_all_missing",
                    message=f"Outcome group {group_label} has no reported applicable values after Stage 4.",
                    study_unit_id=study_unit_id,
                )

        for field_name, total_count in applicable_counts.items():
            if total_count <= 0:
                continue
            ratio = not_reported_counts[field_name] / total_count
            report.field_not_reported_ratio[field_name] = ratio
            if ratio > 0.5:
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="field_sparse",
                    message=f"Field {field_name} is Not Reported in {not_reported_counts[field_name]}/{total_count} applicable rows.",
                    field_name=field_name,
                )

        report.duplicate_row_count = len(report.duplicate_row_signatures)
        report.is_valid = report.error_count == 0
        return report

    def _build_study_unit(self, payload: Dict[str, object], index: int) -> StudyUnit:
        return StudyUnit(
            unit_id=self._string(payload.get("unit_id")) or f"SU-{index}",
            label=self._string(payload.get("label")) or f"Study Unit {index}",
            arms=self._normalize_arms(payload.get("arms")),
            population_note=self._string(payload.get("population_note")),
            intervention=self._string(payload.get("intervention")),
            comparison=self._string(payload.get("comparison")),
        )

    @staticmethod
    def _default_study_unit() -> StudyUnit:
        return StudyUnit(unit_id="SU-1", label="Main Study", arms=["", ""])

    @staticmethod
    def _paper_profile_as_dict(profile: PaperProfile) -> Dict[str, str]:
        return {
            "title": profile.title,
            "year": profile.year,
            "journal": profile.journal,
            "authors": profile.authors,
            "study_design": profile.study_design,
            "country": profile.country,
            "sample_size": profile.sample_size,
            "follow_up": profile.follow_up,
        }

    @staticmethod
    def _study_unit_as_dict(study_unit: StudyUnit) -> Dict[str, object]:
        return {
            "unit_id": study_unit.unit_id,
            "label": study_unit.label,
            "arms": list(study_unit.arms),
            "population_note": study_unit.population_note,
            "intervention": study_unit.intervention,
            "comparison": study_unit.comparison,
        }

    @staticmethod
    def _row_candidate_as_dict(candidate: RowCandidate) -> Dict[str, str]:
        return {
            "row_id": candidate.row_id,
            "study_unit_id": candidate.study_unit_id,
            "outcome_name": candidate.outcome_name,
            "outcome_type": candidate.outcome_type,
            "timepoint": candidate.timepoint,
            "value_type": candidate.value_type,
            "outcome_unit": candidate.outcome_unit,
            "statistic_description": candidate.statistic_description,
            "note": candidate.note,
        }

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

    @staticmethod
    def _normalize_arms(value: object) -> List[str]:
        if isinstance(value, list):
            arms = []
            for item in value:
                text = PipelineOrchestrator._string(item)
                if text:
                    arms.append(text)
        else:
            text = PipelineOrchestrator._string(value)
            arms = [text] if text else []

        if not arms:
            return ["", ""]
        if len(arms) == 1:
            return [arms[0], ""]
        return arms

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = (mode or "legacy").strip().lower()
        if normalized in {"legacy", "phase1", "phase2"}:
            return normalized
        return "legacy"

    @staticmethod
    def _string(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        return str(value).strip()

    @staticmethod
    def _record_stage_error(state: PipelineState, stage_name: str, exc: Exception) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        state.stage_errors[stage_name] = message
        logger.exception("%s failed for paper_id=%s", stage_name, state.paper_id)

    @staticmethod
    def _normalize_row_for_validation(row: ExtractionRow) -> None:
        row.study_unit_id = PipelineOrchestrator._string(row.study_unit_id)
        row.outcome_name = PipelineOrchestrator._string(row.outcome_name)
        row.outcome_type = RobustJSONParser._normalize_outcome_type(row.outcome_type)
        row.timepoint = PipelineOrchestrator._string(row.timepoint)
        row.value_type = RobustJSONParser._normalize_value_type(row.value_type)
        row.outcome_unit = PipelineOrchestrator._string(row.outcome_unit)
        row.statistic_description = PipelineOrchestrator._string(row.statistic_description)
        row.note = RobustJSONParser._clean_whitespace(row.note)
        row.error = RobustJSONParser._clean_whitespace(row.error)

        applicable_fields = set(PipelineOrchestrator._applicable_value_fields(row.outcome_type))
        for field_name in CANONICAL_VALUE_FIELDS:
            default_value = RobustJSONParser._default_field_value(row.outcome_type, field_name)
            cell = row.values.get(field_name)
            if cell is None:
                cell = ExtractedCell(value=default_value, evidence="")
                row.values[field_name] = cell

            if field_name not in applicable_fields:
                cell.value = ""
                cell.evidence = ""
                continue

            normalized_value = PipelineOrchestrator._normalize_reported_value(cell.value)
            cell.value = normalized_value
            cell.evidence = RobustJSONParser._clean_whitespace(cell.evidence) if normalized_value != "Not Reported" else ""

    @staticmethod
    def _normalize_reported_value(value: object) -> str:
        text = RobustJSONParser._clean_whitespace(value)
        if not text:
            return "Not Reported"
        if text.casefold() in {"not reported", "nr", "n/r", "na", "n/a", "not available", "missing", "not stated"}:
            return "Not Reported"
        return text

    @staticmethod
    def _applicable_value_fields(outcome_type: str) -> List[str]:
        normalized = RobustJSONParser._normalize_outcome_type(outcome_type)
        if normalized == "continuous":
            return [field_name for field_name in CANONICAL_VALUE_FIELDS if field_name not in BINARY_ONLY_FIELDS]
        if normalized == "binary":
            return [field_name for field_name in CANONICAL_VALUE_FIELDS if field_name not in CONTINUOUS_ONLY_FIELDS]
        return []

    @staticmethod
    def _row_has_reported_value(row: ExtractionRow) -> bool:
        applicable_fields = PipelineOrchestrator._applicable_value_fields(row.outcome_type)
        if not applicable_fields:
            applicable_fields = list(CANONICAL_VALUE_FIELDS)
        for field_name in applicable_fields:
            cell = row.values.get(field_name)
            if cell and cell.value not in {"", "Not Reported"}:
                return True
        return False

    @staticmethod
    def _row_signature(row: ExtractionRow) -> Tuple[str, str, str, str]:
        return (
            row.study_unit_id.strip().casefold(),
            row.outcome_name.strip().casefold(),
            row.timepoint.strip().casefold(),
            (row.value_type or "other").strip().casefold(),
        )

    @staticmethod
    def _format_row_signature(signature: Tuple[str, str, str, str]) -> str:
        study_unit_id, outcome_name, timepoint, value_type = signature
        return f"{study_unit_id}/{outcome_name}/{timepoint or '[no-timepoint]'}/{value_type or 'other'}"

    @staticmethod
    def _add_validation_issue(
        report: ValidationReport,
        *,
        severity: str,
        code: str,
        message: str,
        row_id: str = "",
        study_unit_id: str = "",
        field_name: str = "",
    ) -> None:
        normalized_severity = severity.lower().strip() or "warning"
        report.issues.append(
            ValidationIssue(
                severity=normalized_severity,
                code=code,
                message=message,
                row_id=row_id,
                study_unit_id=study_unit_id,
                field_name=field_name,
            )
        )
        if normalized_severity == "error":
            report.error_count += 1
        else:
            report.warning_count += 1
