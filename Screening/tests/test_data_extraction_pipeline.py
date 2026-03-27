from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENING_DIR = ROOT_DIR / "Screening"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCREENING_DIR) not in sys.path:
    sys.path.insert(0, str(SCREENING_DIR))

import fitz
from openpyxl import Workbook, load_workbook

from Screening.data_extraction.models import (
    ExtractedCell,
    ExtractionRow,
    Paper,
    PaperProfile,
    PipelineState,
    RowCandidate,
    StudyUnit,
)
from Screening.data_extraction.output import _infer_rayyan_id, csv_to_excel, state_to_final_rows
from Screening.data_extraction.parsing import RobustJSONParser
from Screening.data_extraction.pdf import discover_pdfs, extract_pdf_title, parse_pages_spec, select_targeted_pages
from Screening.data_extraction.service import ExtractionRequest, PipelineOrchestrator
from Screening.data_extraction.template import read_template_columns


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


class _RecoveringFakeLLM(_FakeLLM):
    def __init__(self) -> None:
        self.stage4_calls: dict[str, int] = {}

    async def extract_text(self, *, pdf_bytes: bytes, filename: str, prompt: str) -> str:
        if "Stage 4: Row Extraction" in prompt and '"outcome_name": "Hemoglobin"' in prompt:
            call_count = self.stage4_calls.get("R-1", 0) + 1
            self.stage4_calls["R-1"] = call_count
            if call_count == 1:
                return json.dumps(
                    {
                        "row_id": "R-1",
                        "study_unit_id": "SU-1",
                        "outcome_name": "Hemoglobin",
                        "outcome_type": "continuous",
                        "timepoint": "14 weeks",
                        "value_type": "endpoint",
                        "outcome_unit": "g/dl",
                        "statistic_description": "mean, SD",
                        "values": {
                            "Arm1_Mean": {"value": "Not Reported", "evidence": ""},
                            "Arm1_SD": {"value": "Not Reported", "evidence": ""},
                            "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm2_Mean": {"value": "Not Reported", "evidence": ""},
                            "Arm2_SD": {"value": "Not Reported", "evidence": ""},
                            "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                            "Arm1_Events": {"value": "", "evidence": ""},
                            "Arm2_Events": {"value": "", "evidence": ""},
                        },
                    }
                )

            return json.dumps(
                {
                    "row_id": "R-1",
                    "study_unit_id": "SU-1",
                    "outcome_name": "Hemoglobin",
                    "outcome_type": "continuous",
                    "timepoint": "14 weeks",
                    "value_type": "endpoint",
                    "outcome_unit": "g/dl",
                    "statistic_description": "mean, SD",
                    "values": {
                        "Arm1_Mean": {"value": "11.5", "evidence": "after intervention 11.5 卤 0.80 g/dl"},
                        "Arm1_SD": {"value": "0.8", "evidence": "after intervention 11.5 卤 0.80 g/dl"},
                        "Arm1_Total": {"value": "60", "evidence": "n = 60"},
                        "Arm2_Mean": {"value": "11.2", "evidence": "for control 11.2 卤 0.73"},
                        "Arm2_SD": {"value": "0.73", "evidence": "for control 11.2 卤 0.73"},
                        "Arm2_Total": {"value": "60", "evidence": "n = 60"},
                        "Arm1_Events": {"value": "", "evidence": ""},
                        "Arm2_Events": {"value": "", "evidence": ""},
                    },
                }
            )

        return await super().extract_text(pdf_bytes=pdf_bytes, filename=filename, prompt=prompt)


class TestDataExtractionPipeline(unittest.IsolatedAsyncioTestCase):
    def test_read_template_columns_captures_second_row_descriptions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            template_path = Path(tmp_dir) / "template.xlsx"

            wb = Workbook()
            ws = wb.active
            ws.title = "baseline characteristics"
            ws.append(["Title", "Age", "Arm1_Mean"])
            ws.append(["Paper title", "Baseline age in years", "Intervention mean outcome"])
            wb.save(template_path)

            all_columns, llm_columns = read_template_columns(template_path)

            self.assertEqual(all_columns, ["Title", "Age", "Arm1_Mean"])
            self.assertEqual(llm_columns, ["Age", "Arm1_Mean"])

    def test_csv_to_excel_does_not_copy_template_description_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            template_path = tmp_path / "template.xlsx"
            csv_path = tmp_path / "output.csv"
            xlsx_path = tmp_path / "output.xlsx"

            wb = Workbook()
            ws = wb.active
            ws.title = "baseline characteristics"
            ws.append(["Age", "Arm1_Mean"])
            ws.append(["Baseline age in years", "Intervention arm mean at endpoint"])
            wb.save(template_path)

            csv_path.write_text(
                "ID,Title,RelativePath,Age,Arm1_Mean,Error\n"
                "1,Test Paper,resources/test.pdf,42,11.5,\n",
                encoding="utf-8-sig",
            )

            csv_to_excel(csv_path, xlsx_path, template_path)

            result_wb = load_workbook(xlsx_path)
            result_ws = result_wb.active
            self.assertEqual(result_ws.max_row, 2)
            self.assertEqual([cell.value for cell in result_ws[1]], ["ID", "Title", "RelativePath", "Age", "Arm1_Mean", "Error"])
            self.assertEqual([cell.value for cell in result_ws[2]], ["1", "Test Paper", "resources/test.pdf", "42", "11.5", None])
            result_wb.close()

    def test_select_targeted_pages_prefers_relevant_result_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "targeted.pdf"
            with fitz.open() as doc:
                pages = [
                    "Introduction and abstract only.",
                    "Methods and baseline characteristics table for participants.",
                    "Results: Hemoglobin outcome at 14 weeks shown in Table 2.",
                    "Table 2. Hemoglobin mean and SD at 14 weeks for intervention and control.",
                    "Appendix and references.",
                ]
                for text in pages:
                    page = doc.new_page()
                    page.insert_text((72, 72), text)
                doc.save(pdf_path)

            selected = select_targeted_pages(
                pdf_path,
                None,
                keywords=["hemoglobin", "14 weeks", "mean", "sd"],
                anchor_terms=["results", "table", "baseline characteristics"],
                max_pages=4,
            )

            self.assertIsNotNone(selected)
            self.assertIn(3, selected)
            self.assertIn(4, selected)
            self.assertLessEqual(len(selected), 4)

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

    def test_parse_row_candidates_accepts_hierarchical_stage3_payload(self) -> None:
        candidates = RobustJSONParser.parse_row_candidates(
            json.dumps(
                {
                    "study_units": [
                        {
                            "study_unit_id": "SU-1",
                            "comparisons": [
                                {
                                    "comparison_label": "iron vs control",
                                    "outcomes": [
                                        {
                                            "outcome_name": "Hemoglobin",
                                            "timepoints": [
                                                {
                                                    "timepoint": "Week 14",
                                                    "value_types": [
                                                        {
                                                            "value_type": "endpoint",
                                                            "statistic_description": "mean and sd",
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    "row_candidates": [
                        {
                            "row_id": "LLM-1",
                            "study_unit_id": "su-1",
                            "outcome_name": "haemoglobin",
                            "outcome_type": "continuous",
                            "timepoint": "Week 14",
                            "value_type": "endpoint_value",
                            "outcome_unit": "g/dl",
                            "statistic_description": "mean and sd",
                            "source_basis": ["table"],
                            "uncertainty": "medium",
                            "evidence_location": "Table 2",
                        }
                    ],
                }
            )
        )

        normalized = RobustJSONParser.normalize_row_candidates(candidates, valid_study_unit_ids=["SU-1"])

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0].study_unit_id, "SU-1")
        self.assertEqual(normalized[0].outcome_name, "Hemoglobin")
        self.assertEqual(normalized[0].timepoint, "14 weeks")
        self.assertEqual(normalized[0].value_type, "endpoint")
        self.assertEqual(normalized[0].statistic_description, "mean, SD")
        self.assertIn("source=table", normalized[0].note)
        self.assertIn("uncertainty=medium", normalized[0].note)

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

    async def test_phase2_recovery_retries_sparse_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / "rayyan-356507246 Arcanjo 2012.pdf"
            with fitz.open() as doc:
                for text in (
                    "Methods and baseline characteristics.",
                    "Results Hemoglobin 14 weeks intervention 11.5 ± 0.80 and control 11.2 ± 0.73.",
                    "Table 2 Hemoglobin mean SD and sample size n = 60 per arm.",
                ):
                    page = doc.new_page()
                    page.insert_text((72, 72), text)
                doc.save(pdf_path)

            llm = _RecoveringFakeLLM()
            orchestrator = PipelineOrchestrator(llm_client=llm, project_dir=Path(tmp_dir))
            state = await orchestrator.build_extraction_rows(
                paper=Paper(paper_id=1, path=pdf_path, title="Arcanjo 2012"),
                request=ExtractionRequest(
                    llm_columns=[],
                    pages_spec=None,
                    project_type="PICOS",
                    pico_dict={"s": "RCT", "p": "preschoolers", "i": "iron", "c": "control", "o": "hemoglobin", "es": ""},
                ),
            )

            self.assertEqual(llm.stage4_calls["R-1"], 2)
            self.assertEqual(state.extraction_rows[0].values["Arm1_Mean"].value, "11.5")
            self.assertEqual(state.extraction_rows[0].values["Arm2_Mean"].value, "11.2")
            self.assertEqual(state.validation_report.recovery_attempt_count, 1)
            self.assertEqual(state.validation_report.recovery_success_count, 1)
            self.assertEqual(state.validation_report.recovery_recovered_row_ids, ["R-1"])
            self.assertEqual(state.validation_report.error_type_counts["false_not_reported"], 1)

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

    def test_parse_extraction_rows_normalizes_field_level_metadata_and_composite_values(self) -> None:
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
            ),
        ]

        parsed = RobustJSONParser.parse_extraction_rows(
            json.dumps(
                [
                    {
                        "row_id": "R-1",
                        "outcome_type": "continuous",
                        "values": {
                            "Arm1_Mean": {
                                "value": "11.5 ± 0.80",
                                "evidence_span": "after intervention 11.5 ± 0.80 g/dl",
                                "evidence_location": "Table 2",
                                "confidence": "high",
                                "missing_reason": "reported",
                            },
                            "Arm1_Total": {
                                "value": "n = 60",
                                "evidence_span": "n = 60",
                                "evidence_location": "Table 2",
                                "confidence": "high",
                                "missing_reason": "reported",
                            },
                            "Arm2_Mean": {
                                "value": "11.2 ± 0.73",
                                "evidence_span": "for control 11.2 ± 0.73",
                                "evidence_location": "Table 2",
                                "confidence": "high",
                                "missing_reason": "reported",
                            },
                            "Arm2_Total": {
                                "value": "60",
                                "evidence_span": "n = 60",
                                "evidence_location": "Table 2",
                                "confidence": "high",
                                "missing_reason": "reported",
                            },
                            "Arm1_Events": {
                                "value": "",
                                "evidence_span": "",
                                "evidence_location": "",
                                "confidence": "high",
                                "missing_reason": "not_applicable",
                            },
                            "Arm2_Events": {
                                "value": "",
                                "evidence_span": "",
                                "evidence_location": "",
                                "confidence": "high",
                                "missing_reason": "not_applicable",
                            },
                        },
                    },
                    {
                        "row_id": "R-2",
                        "outcome_type": "binary",
                        "values": {
                            "Arm1_Events": {
                                "value": "12/60 (20%)",
                                "evidence_span": "Anemia prevalence reduced to 12/60 (20%)",
                                "evidence_location": "Results text",
                                "confidence": "medium",
                                "missing_reason": "reported",
                            },
                            "Arm2_Events": {
                                "value": "27/60 (45%)",
                                "evidence_span": "Control remained at 27/60 (45%)",
                                "evidence_location": "Results text",
                                "confidence": "medium",
                                "missing_reason": "reported",
                            },
                            "Arm1_Mean": {
                                "value": "",
                                "evidence_span": "",
                                "evidence_location": "",
                                "confidence": "high",
                                "missing_reason": "not_applicable",
                            },
                            "Arm2_Mean": {
                                "value": "",
                                "evidence_span": "",
                                "evidence_location": "",
                                "confidence": "high",
                                "missing_reason": "not_applicable",
                            },
                        },
                    },
                ]
            ),
            row_candidates,
        )

        normalized = RobustJSONParser.normalize_extraction_rows(parsed, row_candidates)

        self.assertEqual(normalized[0].values["Arm1_Mean"].value, "11.5")
        self.assertEqual(normalized[0].values["Arm1_SD"].value, "0.80")
        self.assertEqual(normalized[0].values["Arm1_Total"].value, "60")
        self.assertEqual(normalized[1].values["Arm1_Events"].value, "12")
        self.assertEqual(normalized[1].values["Arm1_Total"].value, "60")
        self.assertEqual(normalized[1].values["Arm2_Events"].value, "27")
        self.assertEqual(normalized[1].values["Arm2_Total"].value, "60")
        self.assertIn("confidence=medium", normalized[1].note)
        self.assertIn("location=Results text", normalized[1].note)

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

    def test_validation_report_exposes_structured_error_statistics(self) -> None:
        orchestrator = PipelineOrchestrator(llm_client=_FakeLLM(), project_dir=Path.cwd())
        state = PipelineState(
            paper_id=2,
            title="Stats Test",
            relative_path="resources/test.pdf",
            study_units=[StudyUnit(unit_id="SU-1", label="Main Study", arms=["intervention", "control"])],
            row_candidates=[
                RowCandidate(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                )
            ],
            extraction_rows=[
                ExtractionRow(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                    note="candidate_outcome_mismatch=Anaemia | candidate_timepoint_mismatch=baseline",
                    values={
                        "Arm1_Mean": ExtractedCell(value="mean 11.5", evidence="control mean 11.5"),
                        "Arm1_SD": ExtractedCell(value="0.8", evidence="control sd 0.8"),
                        "Arm1_Total": ExtractedCell(value="60", evidence="control n = 60"),
                        "Arm2_Mean": ExtractedCell(value="11.2", evidence="intervention mean 11.2"),
                        "Arm2_SD": ExtractedCell(value="0.7", evidence="intervention sd 0.7"),
                        "Arm2_Total": ExtractedCell(value="60", evidence="intervention n = 60"),
                    },
                )
            ],
        )

        report = orchestrator.validate_state(state)
        summary = report.to_summary_dict()

        self.assertEqual(report.error_type_counts["wrong_outcome"], 1)
        self.assertEqual(report.error_type_counts["wrong_timepoint"], 1)
        self.assertEqual(report.error_type_counts["arm_swap"], 1)
        self.assertEqual(report.error_type_counts["value_parse_failure"], 1)
        self.assertIn("error_type_counts", summary)
        self.assertEqual(summary["error_type_counts"]["arm_swap"], 1)
        self.assertIsInstance(summary["issues"], list)


class RobustJSONParserHelperTests(unittest.TestCase):
    def test_parse_json_payload_direct(self) -> None:
        parsed = RobustJSONParser.parse_json_payload('{"a": 1, "b": "x"}')
        self.assertEqual(parsed["a"], 1)
        self.assertEqual(parsed["b"], "x")

    def test_parse_json_payload_markdown_wrapped(self) -> None:
        text = "```json\n{\"a\": 1}\n```"
        parsed = RobustJSONParser.parse_json_payload(text)
        self.assertEqual(parsed["a"], 1)

    def test_parse_json_payload_brace_extraction(self) -> None:
        text = "prefix ... {\"a\": 1, \"b\": [2]} ... suffix"
        parsed = RobustJSONParser.parse_json_payload(text)
        self.assertEqual(parsed["a"], 1)
        self.assertEqual(parsed["b"], [2])

    def test_parse_json_payload_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            RobustJSONParser.parse_json_payload("")

    def test_parse_json_payload_no_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            RobustJSONParser.parse_json_payload("no json here")

    def test_normalize_timepoint_variants(self) -> None:
        self.assertEqual(RobustJSONParser._normalize_timepoint("14 weeks"), "14 weeks")
        self.assertEqual(RobustJSONParser._normalize_timepoint("Week 14"), "14 weeks")
        self.assertEqual(RobustJSONParser._normalize_timepoint("at 14 wks"), "14 weeks")

    def test_normalize_outcome_type_infers(self) -> None:
        self.assertEqual(RobustJSONParser._normalize_outcome_type("", statistic_description="mean, SD"), "continuous")
        self.assertEqual(RobustJSONParser._normalize_outcome_type("", statistic_description="events, total"), "binary")

    def test_normalize_value_type_aliases(self) -> None:
        self.assertEqual(RobustJSONParser._normalize_value_type("endpoint_value"), "endpoint")
        self.assertEqual(RobustJSONParser._normalize_value_type("delta"), "change_from_baseline")

    def test_extract_mean_sd_from_plus_minus(self) -> None:
        self.assertEqual(RobustJSONParser._extract_mean_sd_pair("11.5 ± 0.80", ""), ("11.5", "0.80"))

    def test_extract_events_total_from_fraction(self) -> None:
        self.assertEqual(RobustJSONParser._extract_events_total_pair("12/60", ""), ("12", "60"))

    def test_is_effect_only_filters_effect_measures(self) -> None:
        self.assertTrue(
            RobustJSONParser._is_effect_only_row_candidate(
                RowCandidate(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="relative risk",
                    outcome_type="other",
                    timepoint="",
                    value_type="other",
                    statistic_description="",
                    note="",
                )
            )
        )
        self.assertFalse(
            RobustJSONParser._is_effect_only_row_candidate(
                RowCandidate(
                    row_id="R-2",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                    statistic_description="mean, SD",
                    note="",
                )
            )
        )


class DataExtractionPDFTests(unittest.TestCase):
    def test_extract_pdf_title_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "meta.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "Body")
                doc.set_metadata({"title": "My Paper Title"})
                doc.save(pdf_path)
            self.assertEqual(extract_pdf_title(pdf_path), "My Paper Title")

    def test_extract_pdf_title_fallback_to_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "fallback.pdf"
            with fitz.open() as doc:
                doc.new_page().insert_text((72, 72), "A long title for fallback\nSecond line")
                doc.set_metadata({"title": "abc"})
                doc.save(pdf_path)
            self.assertEqual(extract_pdf_title(pdf_path), "A long title for fallback")

    def test_discover_pdfs_nested_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a").mkdir()
            (root / "b" / "c").mkdir(parents=True)
            for path in (root / "a" / "one.pdf", root / "b" / "c" / "two.pdf"):
                with fitz.open() as doc:
                    doc.new_page().insert_text((72, 72), "Doc")
                    doc.save(path)
            papers = discover_pdfs(root)
            self.assertEqual(len(papers), 2)
            self.assertEqual([p.paper_id for p in papers], [1, 2])
            self.assertTrue(all(isinstance(p, Paper) for p in papers))

    def test_parse_pages_spec_variants(self) -> None:
        self.assertIsNone(parse_pages_spec("all"))
        self.assertEqual(parse_pages_spec("1-3,5"), [1, 2, 3, 5])


class OutputEdgeCaseTests(unittest.TestCase):
    def test_state_to_final_rows_maps_metadata(self) -> None:
        state = PipelineState(
            paper_id=1,
            title="Fallback Title",
            relative_path="resources/rayyan-1 demo.pdf",
            profile=PaperProfile(title="Study Title", year="2020", country="UK", study_design="RCT"),
            study_units=[StudyUnit(unit_id="SU-1", label="Main", arms=["A", "B"])],
            extraction_rows=[
                ExtractionRow(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hemoglobin",
                    outcome_type="continuous",
                    timepoint="14 weeks",
                    value_type="endpoint",
                    outcome_unit="g/dl",
                    statistic_description="mean, SD",
                    values={
                        "Arm1_Mean": ExtractedCell(value="11.5", evidence=""),
                        "Arm1_SD": ExtractedCell(value="0.8", evidence=""),
                        "Arm1_Total": ExtractedCell(value="60", evidence=""),
                        "Arm2_Mean": ExtractedCell(value="11.2", evidence=""),
                        "Arm2_SD": ExtractedCell(value="0.7", evidence=""),
                        "Arm2_Total": ExtractedCell(value="60", evidence=""),
                    },
                )
            ],
        )

        value_rows, _ = state_to_final_rows(state)
        self.assertEqual(value_rows[0]["Year"], "2020")
        self.assertEqual(value_rows[0]["Study_ID"], "Study Title")
        self.assertEqual(value_rows[0]["Country"], "UK")

    def test_state_to_final_rows_chinese_aliases(self) -> None:
        state = PipelineState(
            paper_id=1,
            title="T",
            relative_path="resources/x.pdf",
            profile=PaperProfile(title="Study", year="2020", country="CN"),
            study_units=[StudyUnit(unit_id="SU-1", arms=["A", "B"])],
            extraction_rows=[
                ExtractionRow(
                    row_id="R-1",
                    study_unit_id="SU-1",
                    outcome_name="Hb",
                    outcome_type="continuous",
                    timepoint="",
                    value_type="endpoint",
                    values={},
                )
            ],
        )
        value_rows, _ = state_to_final_rows(state)
        self.assertEqual(value_rows[0]["结局指标"], "Hb")
        self.assertEqual(value_rows[0]["结局定义（终点值或变化值）"], "终点值")

    def test_infer_rayyan_id_extracts_from_path(self) -> None:
        self.assertEqual(_infer_rayyan_id("rayyan-356507246 Arcanjo.pdf", "fallback"), "rayyan-356507246")

    def test_infer_rayyan_id_fallback_to_stem(self) -> None:
        self.assertEqual(_infer_rayyan_id("MyPaper.pdf", "fallback"), "MyPaper")


if __name__ == "__main__":
    unittest.main()
