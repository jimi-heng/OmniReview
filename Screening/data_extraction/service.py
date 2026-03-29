# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import json
import logging
import re
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
from .pdf import build_targeted_pdf_bytes, load_pdf_bytes
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
                pdf_bytes=self._build_stage3_pdf_bytes(
                    paper=paper,
                    pages_spec=request.pages_spec,
                    pico_dict=pico_dict,
                    profile=state.profile,
                    study_units=state.study_units,
                    fallback_pdf_bytes=pdf_bytes,
                ),
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
            pages_spec=request.pages_spec,
            project_type=request.project_type,
            study_units=state.study_units,
            row_candidates=state.row_candidates,
            profile=state.profile,
        )
        try:
            state.validation_report = await self._run_stage5_with_recovery(
                state=state,
                paper=paper,
                request=request,
                pdf_bytes=pdf_bytes,
            )
            self._log_phase2_validation_summary(state)
        except Exception as exc:
            self._record_stage_error(state, "stage5", exc)

        self._consolidate_metadata(state)
        self._filter_invalid_rows(state)
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
                pdf_bytes=self._build_stage3_pdf_bytes(
                    paper=paper,
                    pages_spec=request.pages_spec,
                    pico_dict=pico_dict,
                    profile=state.profile,
                    study_units=state.study_units,
                    fallback_pdf_bytes=pdf_bytes,
                ),
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
            pages_spec=request.pages_spec,
            project_type=request.project_type,
            study_units=state.study_units,
            row_candidates=state.row_candidates,
            profile=state.profile,
        )
        try:
            state.validation_report = await self._run_stage5_with_recovery(
                state=state,
                paper=paper,
                request=request,
                pdf_bytes=pdf_bytes,
            )
            self._log_phase2_validation_summary(state)
        except Exception as exc:
            self._record_stage_error(state, "stage5", exc)
        self._consolidate_metadata(state)
        self._filter_invalid_rows(state)
        state.final_value_rows, state.final_evidence_rows = state_to_final_rows(state)
        return state

    def validate_state(self, state: PipelineState) -> ValidationReport:
        report = self._run_stage5(state=state)
        state.validation_report = report
        return report

    def _consolidate_metadata(self, state: PipelineState) -> None:
        profile = state.profile
        for unit in state.study_units:
            unit.population_summary = unit.population_summary or profile.population_summary
            unit.inclusion_criteria = unit.inclusion_criteria or profile.inclusion_criteria
            unit.exclusion_criteria = unit.exclusion_criteria or profile.exclusion_criteria
            unit.age_info = unit.age_info or profile.age_info
            unit.gender_info = unit.gender_info or profile.gender_info
            unit.analysis_sample_size = unit.analysis_sample_size or profile.analysis_sample_size
            unit.randomized_sample_size = unit.randomized_sample_size or profile.randomized_sample_size
            unit.arm1_n = unit.arm1_n or profile.arm1_n
            unit.arm2_n = unit.arm2_n or profile.arm2_n

    def _filter_invalid_rows(self, state: PipelineState) -> None:
        if not state.extraction_rows:
            return

        filtered: List[ExtractionRow] = []
        removed: List[ExtractionRow] = []
        for row in state.extraction_rows:
            if self._is_effect_only_row(row):
                removed.append(row)
            else:
                filtered.append(row)

        if removed:
            for row in removed:
                self._add_validation_issue(
                    state.validation_report,
                    severity="warning",
                    code="effect_only_row_removed",
                    message=f"Row {row.row_id} appeared to represent an effect-size-only statistic and was removed before final output.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )
        state.extraction_rows = filtered

    @staticmethod
    def _is_effect_only_row(row: ExtractionRow) -> bool:
        outcome_name = RobustJSONParser._clean_whitespace(row.outcome_name)
        statistic_description = RobustJSONParser._clean_whitespace(row.statistic_description)
        note = RobustJSONParser._clean_whitespace(row.note)
        combined = " ".join(part for part in (outcome_name, statistic_description, note) if part)

        if outcome_name.casefold() in {
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
        }:
            return True

        if not RobustJSONParser._looks_like_effect_measure(combined):
            return False

        if PipelineOrchestrator._row_has_reported_value(row):
            return False

        return True

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
            title=self._normalize_metadata_text(payload.get("title")),
            year=self._normalize_metadata_text(payload.get("year")),
            journal=self._normalize_metadata_text(payload.get("journal")),
            authors=self._normalize_metadata_text(payload.get("authors")),
            study_design=self._normalize_metadata_text(payload.get("study_design")),
            country=self._normalize_metadata_text(payload.get("country")),
            sample_size=self._normalize_metadata_text(payload.get("sample_size")),
            follow_up=self._normalize_metadata_text(payload.get("follow_up")),
            population_summary=self._normalize_metadata_text(payload.get("population_summary")),
            inclusion_criteria=self._normalize_metadata_text(payload.get("inclusion_criteria")),
            exclusion_criteria=self._normalize_metadata_text(payload.get("exclusion_criteria")),
            age_info=self._normalize_metadata_text(payload.get("age_info")),
            gender_info=self._normalize_metadata_text(payload.get("gender_info")),
            analysis_sample_size=self._normalize_sample_size_text(payload.get("analysis_sample_size")),
            randomized_sample_size=self._normalize_sample_size_text(payload.get("randomized_sample_size")),
            arm1_n=self._normalize_sample_size_text(payload.get("arm1_n")),
            arm2_n=self._normalize_sample_size_text(payload.get("arm2_n")),
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
        pages_spec: Optional[List[int]],
        project_type: str,
        study_units: List[StudyUnit],
        row_candidates: List[RowCandidate],
        profile: PaperProfile,
    ) -> List[ExtractionRow]:
        study_unit_by_id = {study_unit.unit_id: study_unit for study_unit in study_units}
        extraction_rows: List[ExtractionRow] = []
        for candidate in row_candidates:
            study_unit = study_unit_by_id.get(candidate.study_unit_id, self._default_study_unit())
            try:
                raw_text = await self._call_stage(
                    stage_name=f"stage4:{candidate.row_id}",
                    pdf_bytes=self._build_row_pdf_bytes(
                        paper=paper,
                        pages_spec=pages_spec,
                        study_unit=study_unit,
                        candidate=candidate,
                        fallback_pdf_bytes=pdf_bytes,
                    ),
                    filename=paper.path.name,
                    prompt=get_stage4_prompt(
                        project_type=project_type,
                        paper_id=paper.paper_id,
                        paper_profile=self._paper_profile_as_dict(profile),
                        study_unit=self._study_unit_as_dict(study_unit),
                        row_candidate=self._row_candidate_as_dict(candidate),
                    ),
                )
                parsed_rows = self._parser.parse_extraction_rows(raw_text, [candidate])
                extraction_rows.extend(self._parser.normalize_extraction_rows(parsed_rows, [candidate]))
            except Exception as exc:
                stage_key = f"stage4:{candidate.row_id}"
                self._record_stage_error(state, stage_key, exc)
                extraction_rows.append(self._blank_extraction_row(candidate, error=str(exc)))
        return extraction_rows

    async def _run_stage5_with_recovery(
        self,
        *,
        state: PipelineState,
        paper: Paper,
        request: ExtractionRequest,
        pdf_bytes: bytes,
    ) -> ValidationReport:
        initial_report = self._run_stage5(state=state)
        candidate_by_id = {candidate.row_id: candidate for candidate in state.row_candidates}
        study_unit_by_id = {study_unit.unit_id: study_unit for study_unit in state.study_units}
        recovery_candidates = self._identify_recovery_candidates(state=state, report=initial_report)
        if not recovery_candidates:
            state.validation_report = initial_report
            return initial_report

        row_by_id = {row.row_id: row for row in state.extraction_rows}
        attempted_row_ids: List[str] = []
        recovered_row_ids: List[str] = []

        for candidate in recovery_candidates:
            attempted_row_ids.append(candidate.row_id)
            current_row = row_by_id.get(candidate.row_id, self._blank_extraction_row(candidate, error="Missing before recovery."))
            study_unit = study_unit_by_id.get(candidate.study_unit_id, self._default_study_unit())
            try:
                raw_text = await self._call_stage(
                    stage_name=f"stage5:recovery:{candidate.row_id}",
                    pdf_bytes=self._build_row_pdf_bytes(
                        paper=paper,
                        pages_spec=request.pages_spec,
                        study_unit=study_unit,
                        candidate=candidate,
                        fallback_pdf_bytes=pdf_bytes,
                        recovery=True,
                    ),
                    filename=paper.path.name,
                    prompt=get_stage4_prompt(
                        project_type=request.project_type,
                        paper_id=paper.paper_id,
                        paper_profile=self._paper_profile_as_dict(state.profile),
                        study_unit=self._study_unit_as_dict(study_unit),
                        row_candidate=self._row_candidate_as_dict(candidate),
                    ),
                )
                parsed_rows = self._parser.parse_extraction_rows(raw_text, [candidate])
                recovered_row = self._parser.normalize_extraction_rows(parsed_rows, [candidate])[0]
                merged_row = self._parser.normalize_extraction_rows([current_row, recovered_row], [candidate])[0]
                if self._row_quality_score(merged_row) > self._row_quality_score(current_row):
                    if not recovered_row.error and self._row_quality_score(recovered_row) >= self._row_quality_score(current_row):
                        merged_row.error = ""
                    row_by_id[candidate.row_id] = merged_row
                    recovered_row_ids.append(candidate.row_id)
            except Exception as exc:
                logger.exception("stage5 recovery failed for paper_id=%s row_id=%s", state.paper_id, candidate.row_id)
                row = row_by_id.get(candidate.row_id)
                if row is not None:
                    row.error = self._merge_error_messages(row.error, f"Recovery failed: {exc}")

        state.extraction_rows = [
            row_by_id.get(candidate.row_id, self._blank_extraction_row(candidate, error="Missing after recovery."))
            for candidate in state.row_candidates
        ]
        final_report = self._run_stage5(state=state)
        if recovered_row_ids:
            for row_id in recovered_row_ids:
                candidate = candidate_by_id.get(row_id)
                self._add_validation_issue(
                    final_report,
                    severity="warning",
                    code="false_not_reported_recovered",
                    message=f"Targeted recovery replaced missing values for row {row_id}.",
                    row_id=row_id,
                    study_unit_id=getattr(candidate, "study_unit_id", ""),
                )
        final_report.recovery_attempt_count = len(attempted_row_ids)
        final_report.recovery_success_count = len(recovered_row_ids)
        final_report.recovery_attempted_row_ids = attempted_row_ids
        final_report.recovery_recovered_row_ids = recovered_row_ids
        for candidate in recovery_candidates:
            if candidate.row_id not in recovered_row_ids:
                self._add_validation_issue(
                    final_report,
                    severity="warning",
                    code="recovery_failed",
                    message=f"Targeted recovery did not improve row {candidate.row_id}; original extraction was kept.",
                    row_id=candidate.row_id,
                    study_unit_id=candidate.study_unit_id,
                )
        final_report.error_type_counts = self._summarize_error_type_counts(final_report)
        state.validation_report = final_report
        return final_report

    async def _call_stage(self, *, stage_name: str, pdf_bytes: bytes, filename: str, prompt: str) -> str:
        if self._debug_prompt:
            logger.debug("%s prompt (first 500 chars) for %s: %s", stage_name, filename, prompt[:500])
        return await self._llm.extract_text(pdf_bytes=pdf_bytes, filename=filename, prompt=prompt)

    def _build_stage3_pdf_bytes(
        self,
        *,
        paper: Paper,
        pages_spec: Optional[List[int]],
        pico_dict: Dict[str, str],
        profile: PaperProfile,
        study_units: List[StudyUnit],
        fallback_pdf_bytes: bytes,
    ) -> bytes:
        try:
            return build_targeted_pdf_bytes(
                paper.path,
                pages_spec,
                keywords=self._build_stage3_keywords(pico_dict=pico_dict, profile=profile, study_units=study_units),
                anchor_terms=["methods", "results", "table", "figure", "baseline characteristics", "follow-up"],
            )
        except Exception:
            logger.exception("stage3 targeted slicing failed for paper_id=%s", paper.paper_id)
            return fallback_pdf_bytes

    def _build_row_pdf_bytes(
        self,
        *,
        paper: Paper,
        pages_spec: Optional[List[int]],
        study_unit: StudyUnit,
        candidate: RowCandidate,
        fallback_pdf_bytes: bytes,
        recovery: bool = False,
    ) -> bytes:
        anchor_terms = [
            "results",
            "table",
            "figure",
            "baseline characteristics",
            "methods" if recovery else "",
        ]
        try:
            return build_targeted_pdf_bytes(
                paper.path,
                pages_spec,
                keywords=self._build_row_keywords(study_unit=study_unit, candidate=candidate, recovery=recovery),
                anchor_terms=anchor_terms,
                max_pages=6 if recovery else 8,
            )
        except Exception:
            logger.exception("targeted row slicing failed for paper_id=%s row_id=%s", paper.paper_id, candidate.row_id)
            return fallback_pdf_bytes

    @staticmethod
    def _build_stage3_keywords(
        *,
        pico_dict: Dict[str, str],
        profile: PaperProfile,
        study_units: List[StudyUnit],
    ) -> List[str]:
        keywords = [
            pico_dict.get("o", ""),
            pico_dict.get("p", ""),
            pico_dict.get("i", ""),
            pico_dict.get("c", ""),
            profile.follow_up,
            profile.sample_size,
        ]
        for study_unit in study_units:
            keywords.extend(
                [
                    study_unit.label,
                    study_unit.population_note,
                    study_unit.intervention,
                    study_unit.comparison,
                    *study_unit.arms,
                ]
            )
        return [keyword.strip() for keyword in keywords if isinstance(keyword, str) and keyword.strip()]

    @staticmethod
    def _build_row_keywords(*, study_unit: StudyUnit, candidate: RowCandidate, recovery: bool) -> List[str]:
        keywords = [
            candidate.outcome_name,
            candidate.timepoint,
            candidate.outcome_unit,
            candidate.statistic_description,
            candidate.value_type.replace("_", " "),
            study_unit.intervention,
            study_unit.comparison,
            study_unit.population_note,
            *study_unit.arms,
        ]
        if candidate.outcome_type == "continuous":
            keywords.extend(["mean", "sd", "standard deviation"])
        elif candidate.outcome_type == "binary":
            keywords.extend(["events", "total", "incidence", "prevalence"])
        if recovery:
            keywords.extend(["table", "figure", "results"])
        return [keyword.strip() for keyword in keywords if isinstance(keyword, str) and keyword.strip()]

    def _identify_recovery_candidates(
        self,
        *,
        state: PipelineState,
        report: ValidationReport,
    ) -> List[RowCandidate]:
        candidate_by_id = {candidate.row_id: candidate for candidate in state.row_candidates}
        target_ids: set[str] = set(report.missing_row_ids)

        for row in state.extraction_rows:
            if self._row_missing_ratio(row) >= 0.5 or row.error:
                target_ids.add(row.row_id)

        empty_groups = set(report.empty_outcome_groups)
        for candidate in state.row_candidates:
            group_label = f"{candidate.study_unit_id}:{candidate.outcome_name.casefold()}"
            if group_label in empty_groups:
                target_ids.add(candidate.row_id)

        for issue in report.issues:
            if issue.code in {"duplicate_row_signature", "conflicting_field_values"} and issue.row_id:
                target_ids.update(part.strip() for part in issue.row_id.split(",") if part.strip())

        ordered: List[RowCandidate] = []
        for candidate in state.row_candidates:
            if candidate.row_id in target_ids:
                ordered.append(candidate_by_id[candidate.row_id])
        return ordered

    @staticmethod
    def _row_missing_ratio(row: ExtractionRow) -> float:
        applicable_fields = PipelineOrchestrator._applicable_value_fields(row.outcome_type)
        if not applicable_fields:
            return 0.0
        missing_count = sum(1 for field_name in applicable_fields if row.values.get(field_name, ExtractedCell()).value == "Not Reported")
        return missing_count / len(applicable_fields)

    @staticmethod
    def _row_quality_score(row: ExtractionRow) -> int:
        applicable_fields = PipelineOrchestrator._applicable_value_fields(row.outcome_type)
        if not applicable_fields:
            applicable_fields = list(CANONICAL_VALUE_FIELDS)
        reported_count = sum(
            1
            for field_name in applicable_fields
            if row.values.get(field_name) and row.values[field_name].value not in {"", "Not Reported"}
        )
        evidence_count = sum(
            1
            for field_name in applicable_fields
            if row.values.get(field_name) and RobustJSONParser._clean_whitespace(row.values[field_name].evidence)
        )
        return (reported_count * 10) + evidence_count - (20 if row.error else 0)

    @staticmethod
    def _merge_error_messages(existing: str, new_message: str) -> str:
        left = RobustJSONParser._clean_whitespace(existing)
        right = RobustJSONParser._clean_whitespace(new_message)
        if not left:
            return right
        if not right or left == right:
            return left
        return f"{left} | {right}"

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

            if "candidate_outcome_mismatch=" in row.note:
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="wrong_outcome",
                    message=f"Row {row.row_id} returned an outcome label inconsistent with the requested candidate.",
                    row_id=row.row_id,
                    study_unit_id=row.study_unit_id,
                )
            if "candidate_timepoint_mismatch=" in row.note:
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="wrong_timepoint",
                    message=f"Row {row.row_id} returned a timepoint inconsistent with the requested candidate.",
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
                elif self._is_value_parse_failure(field_name, row.values[field_name].value, row.outcome_type):
                    self._add_validation_issue(
                        report,
                        severity="warning",
                        code="value_parse_failure",
                        message=f"Field {field_name} in row {row.row_id} could not be normalized cleanly.",
                        row_id=row.row_id,
                        study_unit_id=row.study_unit_id,
                        field_name=field_name,
                    )

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

            study_unit = next((unit for unit in state.study_units if unit.unit_id == row.study_unit_id), None)
            if study_unit and self._is_arm_swap_suspected(row, study_unit):
                self._add_validation_issue(
                    report,
                    severity="warning",
                    code="arm_swap",
                    message=f"Row {row.row_id} may have intervention/control evidence assigned to the wrong arm.",
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
                conflicting_fields = self._find_conflicting_fields_for_signature(state.extraction_rows, signature)
                for field_name in conflicting_fields:
                    self._add_validation_issue(
                        report,
                        severity="warning",
                        code="conflicting_field_values",
                        message=f"Duplicate rows for {signature_text} disagree on field {field_name}.",
                        row_id=",".join(row_ids),
                        field_name=field_name,
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
        report.error_type_counts = self._summarize_error_type_counts(report)
        report.is_valid = report.error_count == 0
        return report

    def _build_study_unit(self, payload: Dict[str, object], index: int) -> StudyUnit:
        return StudyUnit(
            unit_id=self._string(payload.get("unit_id")) or f"SU-{index}",
            label=self._string(payload.get("label")) or f"Study Unit {index}",
            arms=self._normalize_arms(payload.get("arms")),
            population_note=self._normalize_metadata_text(payload.get("population_note")),
            intervention=self._normalize_metadata_text(payload.get("intervention")),
            comparison=self._normalize_metadata_text(payload.get("comparison")),
            population_summary=self._normalize_metadata_text(payload.get("population_summary")),
            inclusion_criteria=self._normalize_metadata_text(payload.get("inclusion_criteria")),
            exclusion_criteria=self._normalize_metadata_text(payload.get("exclusion_criteria")),
            age_info=self._normalize_metadata_text(payload.get("age_info")),
            gender_info=self._normalize_metadata_text(payload.get("gender_info")),
            analysis_sample_size=self._normalize_sample_size_text(payload.get("analysis_sample_size")),
            randomized_sample_size=self._normalize_sample_size_text(payload.get("randomized_sample_size")),
            arm1_n=self._normalize_sample_size_text(payload.get("arm1_n")),
            arm2_n=self._normalize_sample_size_text(payload.get("arm2_n")),
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
            "population_summary": profile.population_summary,
            "inclusion_criteria": profile.inclusion_criteria,
            "exclusion_criteria": profile.exclusion_criteria,
            "age_info": profile.age_info,
            "gender_info": profile.gender_info,
            "analysis_sample_size": profile.analysis_sample_size,
            "randomized_sample_size": profile.randomized_sample_size,
            "arm1_n": profile.arm1_n,
            "arm2_n": profile.arm2_n,
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
            "population_summary": study_unit.population_summary,
            "inclusion_criteria": study_unit.inclusion_criteria,
            "exclusion_criteria": study_unit.exclusion_criteria,
            "age_info": study_unit.age_info,
            "gender_info": study_unit.gender_info,
            "analysis_sample_size": study_unit.analysis_sample_size,
            "randomized_sample_size": study_unit.randomized_sample_size,
            "arm1_n": study_unit.arm1_n,
            "arm2_n": study_unit.arm2_n,
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
    def _normalize_metadata_text(value: object) -> str:
        text = RobustJSONParser._clean_whitespace(PipelineOrchestrator._string(value))
        if not text:
            return ""
        if text.casefold() in {"not reported", "nr", "n/r", "na", "n/a", "not available", "missing", "not stated"}:
            return ""
        return text

    @staticmethod
    def _normalize_sample_size_text(value: object) -> str:
        text = PipelineOrchestrator._normalize_metadata_text(value)
        if not text:
            return ""

        match = re.fullmatch(r"(\d[\d,]*)\s*\(\s*-?\d+(?:\.\d+)?\s*%?\s*\)\s*", text)
        if match:
            return match.group(1).replace(",", "")

        tokens = re.findall(r"\d[\d,]*", text)
        if len(tokens) == 1:
            return tokens[0].replace(",", "")
        return text

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
    def _find_conflicting_fields_for_signature(
        rows: List[ExtractionRow],
        signature: Tuple[str, str, str, str],
    ) -> List[str]:
        matching_rows = [row for row in rows if PipelineOrchestrator._row_signature(row) == signature]
        if len(matching_rows) < 2:
            return []

        field_names = set()
        for row in matching_rows:
            field_names.update(PipelineOrchestrator._applicable_value_fields(row.outcome_type))

        conflicting_fields: List[str] = []
        for field_name in sorted(field_names):
            values = {
                row.values[field_name].value
                for row in matching_rows
                if row.values.get(field_name) and row.values[field_name].value not in {"", "Not Reported"}
            }
            if len(values) > 1:
                conflicting_fields.append(field_name)
        return conflicting_fields

    @staticmethod
    def _summarize_error_type_counts(report: ValidationReport) -> Dict[str, int]:
        counts = {
            "missing_rows": report.missing_row_count,
            "duplicate_rows": report.duplicate_row_count,
            "wrong_outcome": 0,
            "wrong_timepoint": 0,
            "arm_swap": 0,
            "value_parse_failure": 0,
            "false_not_reported": 0,
        }
        issue_to_category = {
            "wrong_outcome": "wrong_outcome",
            "wrong_timepoint": "wrong_timepoint",
            "arm_swap": "arm_swap",
            "value_parse_failure": "value_parse_failure",
            "false_not_reported_recovered": "false_not_reported",
        }
        for issue in report.issues:
            category = issue_to_category.get(issue.code)
            if category:
                counts[category] += 1
        return counts

    @staticmethod
    def _is_value_parse_failure(field_name: str, value: str, outcome_type: str) -> bool:
        text = RobustJSONParser._clean_whitespace(value)
        if text in {"", "Not Reported"}:
            return False

        if field_name.endswith("_Total") or field_name.endswith("_Events"):
            return any(char.isalpha() for char in text)
        if outcome_type == "continuous" and field_name.endswith(("_Mean", "_SD")):
            return any(char.isalpha() for char in text) or "/" in text
        return False

    @staticmethod
    def _is_arm_swap_suspected(row: ExtractionRow, study_unit: StudyUnit) -> bool:
        arm1_label = RobustJSONParser._clean_whitespace(study_unit.arms[0] if study_unit.arms else study_unit.intervention).casefold()
        arm2_label = RobustJSONParser._clean_whitespace(study_unit.arms[1] if len(study_unit.arms) > 1 else study_unit.comparison).casefold()
        if not arm1_label or not arm2_label:
            return False

        arm1_evidence = " ".join(
            RobustJSONParser._clean_whitespace(row.values.get(field_name, ExtractedCell()).evidence)
            for field_name in CANONICAL_VALUE_FIELDS
            if field_name.startswith("Arm1_")
        ).casefold()
        arm2_evidence = " ".join(
            RobustJSONParser._clean_whitespace(row.values.get(field_name, ExtractedCell()).evidence)
            for field_name in CANONICAL_VALUE_FIELDS
            if field_name.startswith("Arm2_")
        ).casefold()

        arm1_mentions_other = arm2_label in arm1_evidence and arm1_label not in arm1_evidence
        arm2_mentions_other = arm1_label in arm2_evidence and arm2_label not in arm2_evidence
        return arm1_mentions_other and arm2_mentions_other

    @staticmethod
    def _log_phase2_validation_summary(state: PipelineState) -> None:
        try:
            logger.info(
                "phase2_validation_summary paper_id=%s stats=%s",
                state.paper_id,
                json.dumps(state.validation_report.to_summary_dict(), ensure_ascii=False, sort_keys=True),
            )
        except Exception:
            logger.exception("failed to log phase2 validation summary for paper_id=%s", state.paper_id)

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
