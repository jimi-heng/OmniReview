from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from Screening.data_extraction.models import ExtractedCell, ExtractionRow, Paper, PipelineState, RowCandidate, StudyUnit
from Screening.data_extraction.parsing import RobustJSONParser
from Screening.data_extraction.service import ExtractionRequest, PipelineOrchestrator


class _FakeLLM:
    async def extract_text(self, *, pdf_bytes: bytes, filename: str, prompt: str) -> str:
        if "Stage 1: Paper Profiling" in prompt:
            return json.dumps(
                {
                    "title": "Arcanjo 2012",
                    "year": "2012",
                    "journal": "Journal of Tropical Pediatrics",
                    "authors": "Arcanjo et al.",
                    "study_design": "RCT",
                    "country": "Brazil",
                    "sample_size": "120",
                    "follow_up": "14 weeks",
                }
            )
        if "Stage 2: Study-Unit Inventory" in prompt:
            return json.dumps(
                [
                    {
                        "unit_id": "SU-1",
                        "label": "Main Study",
                        "arms": ["iron-fortified lacteal beverage", "lacteal beverage"],
                        "population_note": "4-year-old preschoolers",
                        "intervention": "iron-fortified lacteal beverage",
                        "comparison": "lacteal beverage",
                    }
                ]
            )
        if "Stage 3: Row Inventory" in prompt:
            return json.dumps(
                [
                    {
                        "row_id": "R-1",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Hemoglobin",
                        "outcome_type": "continuous",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "g/dl",
                        "statistic_description": "mean, SD",
                        "note": "",
                    },
                    {
                        "row_id": "R-2",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Anaemia",
                        "outcome_type": "binary",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "%",
                        "statistic_description": "events, total",
                        "note": "",
                    },
                ]
            )
        if "Stage 4: Row Extraction" in prompt and "Hemoglobin" in prompt:
            return json.dumps(
                [
                    {
                        "row_id": "R-1",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Hemoglobin",
                        "outcome_type": "continuous",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "g/dl",
                        "statistic_description": "mean, SD",
                        "note": "",
                        "values": {
                            "Arm1_Mean": {"value": "11.5", "evidence": "after intervention 11.5 ± 0.80 g/dl"},
                            "Arm1_SD": {"value": "0.8", "evidence": "after intervention 11.5 ± 0.80 g/dl"},
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Mean": {"value": "11.2", "evidence": "for control 11.2 ± 0.73"},
                            "Arm2_SD": {"value": "0.73", "evidence": "for control 11.2 ± 0.73"},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "", "evidence": ""},
                            "Arm2_Events": {"value": "", "evidence": ""},
                        },
                    }
                ]
            )
        if "Stage 4: Row Extraction" in prompt and "Anaemia" in prompt:
            return json.dumps(
                [
                    {
                        "row_id": "R-2",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Anaemia",
                        "outcome_type": "binary",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "%",
                        "statistic_description": "events, total",
                        "note": "",
                        "values": {
                            "Arm1_Mean": {"value": "", "evidence": ""},
                            "Arm1_SD": {"value": "", "evidence": ""},
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Mean": {"value": "", "evidence": ""},
                            "Arm2_SD": {"value": "", "evidence": ""},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "12", "evidence": "Anemia prevalence reduced to 20%"},
                            "Arm2_Events": {"value": "27", "evidence": "No reduction in the control group"},
                        },
                    }
                ]
            )
        return json.dumps([])


class TestDataExtractionPipeline(unittest.IsolatedAsyncioTestCase):
    async def test_build_row_inventory_returns_normalized_stage3_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "rayyan-356507246 Arcanjo 2012.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            orchestrator = PipelineOrchestrator(llm_client=_FakeLLM(), project_dir=Path(tmp_dir))
            state = await orchestrator.build_row_inventory(
                paper=Paper(paper_id=1, path=pdf_path, title="Arcanjo 2012"),
                request=ExtractionRequest(
                    llm_columns=[],
                    pages_spec=None,
                    project_type="PICOS",
                    pico_dict={"s": "RCT", "p": "preschoolers", "i": "iron", "c": "control", "o": "hemoglobin", "es": ""},
                ),
            )

            self.assertEqual(state.stage_errors, {})
            self.assertEqual(len(state.study_units), 1)
            self.assertEqual(len(state.row_candidates), 2)
            self.assertEqual(state.row_candidates[0].row_id, "R-1")
            self.assertEqual(state.row_candidates[0].study_unit_id, "SU-1")
            self.assertEqual(state.row_candidates[0].value_type, "endpoint")
            self.assertEqual(state.row_candidates[1].row_id, "R-2")
            self.assertEqual(state.row_candidates[1].outcome_type, "binary")

    async def test_phase2_pipeline_maps_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "rayyan-356507246 Arcanjo 2012.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            orchestrator = PipelineOrchestrator(llm_client=_FakeLLM(), project_dir=Path(tmp_dir))
            result = await orchestrator.extract(
                paper=Paper(paper_id=1, path=pdf_path, title="Arcanjo 2012"),
                request=ExtractionRequest(
                    llm_columns=[
                        "Year",
                        "Study_ID",
                        "Name_of_Outcome",
                        "Arm1_Mean",
                        "Arm1_SD",
                        "Arm1_Total",
                        "Arm2_Mean",
                        "Arm2_SD",
                        "Arm2_Total",
                        "Arm1_Events",
                        "Arm2_Events",
                        "key",
                        "结局指标",
                        "结局定义（终点值或变化值）",
                        "干预组数据结果(mean/median/events）",
                        "对照组数据结果(mean/median）",
                    ],
                    pages_spec=None,
                    project_type="PICOS",
                    pico_dict={"s": "RCT", "p": "preschoolers", "i": "iron", "c": "control", "o": "hemoglobin", "es": ""},
                    pipeline_mode="phase2",
                ),
            )

            self.assertEqual(result.error, "")
            self.assertEqual(len(result.value_rows), 2)
            self.assertEqual(result.value_rows[0]["Name_of_Outcome"], "Hemoglobin")
            self.assertEqual(result.value_rows[0]["Arm1_Mean"], "11.5")
            self.assertEqual(result.value_rows[0]["结局定义（终点值或变化值）"], "终点值")
            self.assertEqual(result.value_rows[1]["Name_of_Outcome"], "Anaemia")
            self.assertEqual(result.value_rows[1]["Arm1_Events"], "12")
            self.assertEqual(result.value_rows[1]["干预组数据结果(mean/median/events）"], "12")
            self.assertEqual(result.value_rows[1]["对照组数据结果(mean/median）"], "27")

    def test_parse_extraction_rows_preserves_non_applicable_blanks(self) -> None:
        rows = RobustJSONParser.parse_extraction_rows(
            json.dumps(
                [
                    {
                        "row_id": "R-1",
                        "outcome_type": "binary",
                        "values": {
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "12", "evidence": "12 events"},
                            "Arm2_Events": {"value": "27", "evidence": "27 events"},
                        },
                    }
                ]
            ),
            [
                type(
                    "Candidate",
                    (),
                    {
                        "row_id": "R-1",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Anaemia",
                        "outcome_type": "binary",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "%",
                        "statistic_description": "events, total",
                        "note": "",
                    },
                )()
            ],
        )

        self.assertEqual(rows[0].values["Arm1_Mean"].value, "")
        self.assertEqual(rows[0].values["Arm1_SD"].value, "")
        self.assertEqual(rows[0].values["Arm1_Events"].value, "12")
        self.assertEqual(rows[0].values["Arm1_Total"].value, "60")

    def test_normalize_row_candidates_deduplicates_and_reassigns_row_ids(self) -> None:
        normalized = RobustJSONParser.normalize_row_candidates(
            [
                type(
                    "Candidate",
                    (),
                    {
                        "row_id": "LLM-1",
                        "study_unit_id": "UNKNOWN",
                        "outcome_name": " Hemoglobin  ",
                        "outcome_type": "continuous",
                        "timepoint": "14   weeks",
                        "value_type": "",
                        "outcome_unit": "g/dl",
                        "statistic_description": "mean, SD",
                        "note": "",
                    },
                )(),
                type(
                    "Candidate",
                    (),
                    {
                        "row_id": "LLM-2",
                        "study_unit_id": "UNKNOWN",
                        "outcome_name": "Hemoglobin",
                        "outcome_type": "continuous",
                        "timepoint": "14 weeks",
                        "value_type": "other",
                        "outcome_unit": "",
                        "statistic_description": "",
                        "note": "duplicate candidate",
                    },
                )(),
            ],
            valid_study_unit_ids=["SU-1"],
        )

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].row_id, "R-1")
        self.assertEqual(normalized[0].study_unit_id, "SU-1")
        self.assertEqual(normalized[0].outcome_name, "Hemoglobin")
        self.assertEqual(normalized[0].timepoint, "14 weeks")
        self.assertEqual(normalized[0].value_type, "other")

    async def test_build_extraction_rows_returns_stage4_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "rayyan-356507246 Arcanjo 2012.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            orchestrator = PipelineOrchestrator(llm_client=_FakeLLM(), project_dir=Path(tmp_dir))
            state = await orchestrator.build_extraction_rows(
                paper=Paper(paper_id=1, path=pdf_path, title="Arcanjo 2012"),
                request=ExtractionRequest(
                    llm_columns=[],
                    pages_spec=None,
                    project_type="PICOS",
                    pico_dict={"s": "RCT", "p": "preschoolers", "i": "iron", "c": "control", "o": "hemoglobin", "es": ""},
                ),
            )

            self.assertEqual(state.stage_errors, {})
            self.assertEqual(len(state.extraction_rows), 2)
            self.assertEqual(state.extraction_rows[0].row_id, "R-1")
            self.assertEqual(state.extraction_rows[0].values["Arm1_Mean"].value, "11.5")
            self.assertEqual(state.extraction_rows[1].row_id, "R-2")
            self.assertEqual(state.extraction_rows[1].values["Arm1_Mean"].value, "")
            self.assertEqual(state.extraction_rows[1].values["Arm1_Events"].value, "12")
            self.assertEqual(len(state.final_value_rows), 2)
            self.assertTrue(state.validation_report.is_valid)
            self.assertEqual(state.validation_report.error_count, 0)
            self.assertEqual(state.validation_report.warning_count, 0)

    def test_normalize_extraction_rows_repairs_duplicates_and_candidate_metadata(self) -> None:
        row_candidates = [
            RowCandidate(
                row_id="R-1",
                study_unit_id="SU-1",
                outcome_name="Hemoglobin",
                outcome_type="continuous",
                timepoint="14 weeks",
                value_type="endpoint",
                outcome_unit="g/dl",
                statistic_description="mean, SD",
            ),
            RowCandidate(
                row_id="R-2",
                study_unit_id="SU-1",
                outcome_name="Anaemia",
                outcome_type="binary",
                timepoint="14 weeks",
                value_type="endpoint",
                outcome_unit="%",
                statistic_description="events, total",
                note="candidate note",
            ),
        ]

        parsed = RobustJSONParser.parse_extraction_rows(
            json.dumps(
                [
                    {
                        "outcome_type": "continuous",
                        "values": {
                            "Arm1_Mean": {"value": " 11.5 ", "evidence": " after intervention 11.5 "},
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Mean": {"value": "11.2", "evidence": "for control 11.2"},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "99", "evidence": "should be ignored"},
                        },
                    },
                    {
                        "row_id": "R-2",
                        "outcome_type": "binary",
                        "values": {
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                        },
                    },
                    {
                        "row_id": "R-2",
                        "outcome_type": "binary",
                        "note": "from table",
                        "values": {
                            "Arm1_Mean": {"value": "1.5", "evidence": "should be blank"},
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "12", "evidence": "12 events"},
                            "Arm2_Events": {"value": "27", "evidence": "27 events"},
                        },
                    },
                    {
                        "row_id": "R-999",
                        "values": {
                            "Arm1_Mean": {"value": "999", "evidence": "ignore me"},
                        },
                    },
                ]
            ),
            row_candidates,
        )
        normalized = RobustJSONParser.normalize_extraction_rows(parsed, row_candidates)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0].row_id, "R-1")
        self.assertEqual(normalized[0].study_unit_id, "SU-1")
        self.assertEqual(normalized[0].timepoint, "14 weeks")
        self.assertEqual(normalized[0].values["Arm1_Mean"].value, "11.5")
        self.assertEqual(normalized[0].values["Arm1_Events"].value, "")
        self.assertEqual(normalized[1].values["Arm1_Mean"].value, "")
        self.assertEqual(normalized[1].values["Arm1_Events"].value, "12")
        self.assertEqual(normalized[1].values["Arm2_Events"].value, "27")
        self.assertIn("candidate note", normalized[1].note)
        self.assertIn("from table", normalized[1].note)

    def test_normalize_extraction_rows_backfills_missing_requested_rows(self) -> None:
        row_candidates = [
            RowCandidate(
                row_id="R-1",
                study_unit_id="SU-1",
                outcome_name="Hemoglobin",
                outcome_type="continuous",
                timepoint="14 weeks",
                value_type="endpoint",
            ),
            RowCandidate(
                row_id="R-2",
                study_unit_id="SU-1",
                outcome_name="Anaemia",
                outcome_type="binary",
                timepoint="14 weeks",
                value_type="endpoint",
            ),
        ]

        parsed = RobustJSONParser.parse_extraction_rows(
            json.dumps(
                [
                    {
                        "row_id": "R-1",
                        "outcome_type": "continuous",
                        "values": {
                            "Arm1_Mean": {"value": "11.5", "evidence": "11.5"},
                            "Arm2_Mean": {"value": "11.2", "evidence": "11.2"},
                        },
                    }
                ]
            ),
            row_candidates,
        )
        normalized = RobustJSONParser.normalize_extraction_rows(parsed, row_candidates)

        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[1].row_id, "R-2")
        self.assertEqual(normalized[1].error, "Missing from Stage 4 output.")
        self.assertEqual(normalized[1].values["Arm1_Events"].value, "Not Reported")
        self.assertEqual(normalized[1].values["Arm1_Mean"].value, "")

    def test_validate_state_reports_stage5_findings(self) -> None:
        orchestrator = PipelineOrchestrator(llm_client=_FakeLLM(), project_dir=Path.cwd())
        state = PipelineState(
            paper_id=1,
            title="Validation Test",
            relative_path="resources/test.pdf",
            study_units=[StudyUnit(unit_id="SU-1", label="Main Study", arms=["Arm A", "Arm B"])],
            row_candidates=[
                RowCandidate(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                ),
                RowCandidate(
                    row_id="R-2",
                    study_unit_id="SU-1",
                    outcome_name="Anaemia",
                    outcome_type="binary",
                    timepoint="14 weeks",
                    value_type="endpoint",
                ),
            ],
            extraction_rows=[
                ExtractionRow(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                    values={
                        "Arm1_Mean": ExtractedCell(value="", evidence=""),
                        "Arm1_SD": ExtractedCell(value="", evidence=""),
                        "Arm1_Total": ExtractedCell(value="60", evidence="n = 60"),
                        "Arm2_Mean": ExtractedCell(value="11.2", evidence="11.2"),
                        "Arm2_SD": ExtractedCell(value="0.7", evidence="0.7"),
                        "Arm2_Total": ExtractedCell(value="60", evidence="n = 60"),
                    },
                ),
                ExtractionRow(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                    values={
                        "Arm1_Mean": ExtractedCell(value="Not Reported", evidence=""),
                        "Arm1_SD": ExtractedCell(value="", evidence=""),
                        "Arm1_Total": ExtractedCell(value="60", evidence="n = 60"),
                        "Arm2_Mean": ExtractedCell(value="11.2", evidence="11.2"),
                        "Arm2_SD": ExtractedCell(value="0.7", evidence="0.7"),
                        "Arm2_Total": ExtractedCell(value="60", evidence="n = 60"),
                    },
                    error="model output duplicated",
                ),
                ExtractionRow(
                    row_id="R-999",
                    study_unit_id="SU-404",
                    outcome_name="Unexpected",
                    outcome_type="binary",
                    timepoint="",
                    value_type="endpoint",
                    values={
                        "Arm1_Events": ExtractedCell(value="1", evidence="1"),
                        "Arm1_Total": ExtractedCell(value="2", evidence="2"),
                        "Arm2_Events": ExtractedCell(value="3", evidence="3"),
                        "Arm2_Total": ExtractedCell(value="4", evidence="4"),
                    },
                ),
            ],
        )

        report = orchestrator.validate_state(state)

        self.assertFalse(report.is_valid)
        self.assertEqual(report.missing_row_ids, ["R-2"])
        self.assertIn("R-1", report.rows_with_extraction_errors)
        self.assertEqual(state.extraction_rows[-1].row_id, "R-2")
        self.assertIn("SU-1:anaemia", report.empty_outcome_groups)
        self.assertGreater(report.field_not_reported_ratio["Arm1_Mean"], 0.5)
        self.assertGreaterEqual(report.error_count, 3)
        self.assertGreaterEqual(report.warning_count, 2)


if __name__ == "__main__":
    unittest.main()
