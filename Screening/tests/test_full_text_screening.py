import asyncio
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENING_DIR = ROOT_DIR / "Screening"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCREENING_DIR) not in sys.path:
    sys.path.insert(0, str(SCREENING_DIR))

import fitz
import httpx

from Screening.FullTextScreening import (
    discover_pdfs,
    load_pdf_bytes,
    normalize_pico_input,
    parse_pages_spec,
    resolve_runtime_config,
)
from Screening.full_text_screening.models import FullTextPaper, FullTextRequest
from Screening.full_text_screening.orchestrator import process_single_paper
from Screening.full_text_screening.parsing import StructuredOutputError, extract_conclusion, extract_evidence, parse_structured_output
from Screening.full_text_screening.prompts import build_user_prompt
from Screening.full_text_screening.runtime import build_payload


class FullTextScreeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = SimpleNamespace(
            endpoint="https://example.test/responses",
            api_key="test-key",
            model="gpt-4.1",
            timeout=30.0,
            retries=1,
            retry_delay=0.0,
            max_concurrency=1,
            pdf_pages="all",
            selected_pages=None,
            enable_highlight=False,
        )

    def test_parse_pages_spec_supports_ranges(self) -> None:
        self.assertIsNone(parse_pages_spec("all"))
        self.assertEqual(parse_pages_spec("1-3,5"), [1, 2, 3, 5])
        self.assertEqual(parse_pages_spec("5,3-1"), [1, 2, 3, 5])

    def test_load_pdf_bytes_slices_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                for idx in range(3):
                    page = doc.new_page()
                    page.insert_text((72, 72), f"Page {idx + 1}")
                doc.save(pdf_path)

            sliced_bytes = load_pdf_bytes(pdf_path, [1, 3])
            with fitz.open(stream=sliced_bytes, filetype="pdf") as sliced:
                self.assertEqual(sliced.page_count, 2)

    def test_load_pdf_bytes_reads_txt_source_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "sample.txt"
            txt_path.write_bytes(b"Line 1\nLine 2")

            self.assertEqual(load_pdf_bytes(txt_path, [1, 3]), b"Line 1\nLine 2")

    def test_discover_pdfs_includes_pdf_and_txt_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            resources_dir = Path(temp_dir)
            (resources_dir / "alpha.txt").write_text("hello", encoding="utf-8")
            with fitz.open() as doc:
                doc.new_page()
                doc.save(resources_dir / "beta.pdf")

            papers = discover_pdfs(resources_dir)

            self.assertEqual([paper.pdf_path.suffix.lower() for paper in papers], [".txt", ".pdf"])

    def test_resolve_runtime_config_merges_env_and_mapping(self) -> None:
        env = {
            "DMX_API_KEY_1": "test-key",
            "WEB_FULLTEXT_MODEL": "gpt-from-env",
            "WEB_FULLTEXT_TIMEOUT": "120",
        }
        with patch.dict(os.environ, env, clear=False):
            runtime = resolve_runtime_config(
                {"max_concurrency": 9, "pdf_pages": "2-4", "enable_highlight": False},
                parse_pages_spec=parse_pages_spec,
            )

        self.assertEqual(runtime.api_key, "test-key")
        self.assertEqual(runtime.model, "gpt-from-env")
        self.assertEqual(runtime.timeout, 120.0)
        self.assertEqual(runtime.max_concurrency, 9)
        self.assertEqual(runtime.selected_pages, [2, 3, 4])
        self.assertFalse(runtime.enable_highlight)

    def test_parse_structured_output_reads_valid_json(self) -> None:
        parsed = parse_structured_output(
            """
            {
              "decision": "Included",
              "reason": "Population and comparison are explicitly reported.",
              "evidence": {
                "study_design": "randomized trial",
                "population": "adult patients",
                "intervention": "drug A",
                "comparison": "placebo",
                "outcomes": "mortality",
                "extra_rules": ""
              }
            }
            """
        )

        self.assertEqual(parsed["decision"], "Included")
        self.assertEqual(parsed["reason"], "Population and comparison are explicitly reported.")
        self.assertEqual(parsed["evidence"]["comparison"], "placebo")
        self.assertEqual(extract_evidence('{"decision":"Excluded","reason":"No comparator.","evidence":{"comparison":"","population":"","study_design":"","intervention":"","outcomes":"","extra_rules":""}}')["comparison"], "")
        self.assertEqual(extract_conclusion('{"decision":"Excluded","reason":"No comparator.","evidence":{"comparison":"","population":"","study_design":"","intervention":"","outcomes":"","extra_rules":""}}'), "No comparator.")

    def test_parse_structured_output_rejects_invalid_json(self) -> None:
        with self.assertRaises(StructuredOutputError):
            parse_structured_output("Flag: 0\nConclusion: excluded")

    def test_normalize_pico_input_flattens_nested_payload_and_collects_extra_rules(self) -> None:
        normalized = normalize_pico_input(
            {
                "S": "RCT",
                "P": {"group": "Adults", "criteria": ["Age >= 18", "Confirmed diagnosis"]},
                "I": ["Drug A", {"dose": "5 mg daily"}],
                "C": ["Placebo", "Usual care"],
                "O": {"primary": ["Remission", "Adverse events"]},
                "ES": {"language": "English only"},
            }
        )

        self.assertEqual(normalized.study_design, "RCT")
        self.assertEqual(normalized.population, "group: Adults")
        self.assertIn("Drug A", normalized.intervention)
        self.assertIn("dose: 5 mg daily", normalized.intervention)
        self.assertIn("primary: Remission\nAdverse events", normalized.outcomes)
        self.assertIn("Population criteria: Age >= 18\nConfirmed diagnosis", normalized.extra_rules)
        self.assertIn("Extra Rule: language: English only", normalized.extra_rules)
        self.assertIn("S", normalized.raw_fields)
        self.assertIn("p", normalized.normalized_fields)

    def test_build_user_prompt_uses_normalized_fields_instead_of_raw_shapes(self) -> None:
        request = FullTextRequest(
            paper=FullTextPaper(paper_id=1, title="Demo", pdf_path=Path("demo.pdf")),
            pico_dict={
                "P": {"target": "Adults", "notes": "Exclude pediatrics"},
                "E": ["Smoking exposure", {"window": "current"}],
                "C": {"reference": "Non-smokers"},
                "O": {"primary": ["Mortality"]},
                "criteria": ["English only"],
            },
            project_type="PECO",
        )

        prompt = build_user_prompt(request)

        self.assertIn("- Population: target: Adults", prompt)
        self.assertIn("- Exposure: Smoking exposure\nwindow: current", prompt)
        self.assertIn("- Comparison: reference: Non-smokers", prompt)
        self.assertIn("- Outcome: primary: Mortality", prompt)
        self.assertIn("Population notes: Exclude pediatrics", prompt)
        self.assertIn("Extra Rule: English only", prompt)
        self.assertNotIn("{'target': 'Adults'", prompt)

    def test_build_payload_embeds_txt_documents_as_input_text(self) -> None:
        payload = build_payload(
            "gpt-4.1",
            prompt="Screen this paper.",
            filename="paper.txt",
            document_text="Adults received Drug A.",
        )

        content = payload["input"][0]["content"]
        self.assertEqual(content[0]["type"], "input_text")
        self.assertIn("Full-text content from paper.txt", content[0]["text"])
        self.assertIn("Adults received Drug A.", content[0]["text"])
        self.assertEqual(content[1], {"type": "input_text", "text": "Screen this paper."})

    def test_process_single_paper_retries_once_after_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), "Hello")
                doc.save(pdf_path)

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=1, title="Demo", pdf_path=pdf_path),
                pico_dict={"P": "Adults"},
                project_type="PICOS",
                normalized_pico=normalize_pico_input({"P": "Adults"}),
            )
            responses = [
                SimpleNamespace(status_code=200, json=lambda: {"output_text": "not json"}),
                SimpleNamespace(
                    status_code=200,
                    json=lambda: {
                        "output_text": '{"decision":"Included","reason":"Explicit match.","evidence":{"study_design":"","population":"Adults","intervention":"","comparison":"","outcomes":"","extra_rules":""}}'
                    },
                ),
            ]

            async def fake_call_with_retry(*args, **kwargs):
                return responses.pop(0)

            async def run_test() -> None:
                async with httpx.AsyncClient() as client:
                    with (
                        patch("Screening.full_text_screening.orchestrator.call_with_retry", new=AsyncMock(side_effect=fake_call_with_retry)),
                        patch("Screening.full_text_screening.orchestrator.post_with_auth_fallback", new=AsyncMock()),
                    ):
                        result = await process_single_paper(client, self.runtime, request)
                self.assertEqual(result["decision"], "Included")

            asyncio.run(run_test())

    def test_process_single_paper_accepts_txt_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "sample.txt"
            txt_path.write_text("Adults with hypertension received Drug A versus placebo.", encoding="utf-8")

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=3, title="Demo TXT", pdf_path=txt_path),
                pico_dict={"P": "Adults"},
                project_type="PICOS",
                normalized_pico=normalize_pico_input({"P": "Adults"}),
            )

            async def run_test() -> None:
                async with httpx.AsyncClient() as client:
                    with (
                        patch(
                            "Screening.full_text_screening.orchestrator.call_with_retry",
                            new=AsyncMock(
                                return_value=SimpleNamespace(
                                    status_code=200,
                                    json=lambda: {
                                        "output_text": '{"decision":"Included","reason":"Explicit match.","evidence":{"study_design":"","population":"Adults","intervention":"Drug A","comparison":"placebo","outcomes":"","extra_rules":""}}'
                                    },
                                )
                            ),
                        ),
                        patch("Screening.full_text_screening.orchestrator.post_with_auth_fallback", new=AsyncMock()),
                    ):
                        result = await process_single_paper(client, self.runtime, request)
                self.assertEqual(result["decision"], "Included")
                self.assertIsNone(result["hl_path"])

            asyncio.run(run_test())

    def test_process_single_paper_returns_error_after_second_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), "Hello")
                doc.save(pdf_path)

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=2, title="Demo", pdf_path=pdf_path),
                pico_dict={"P": "Adults"},
                project_type="PICOS",
                normalized_pico=normalize_pico_input({"P": "Adults"}),
            )

            async def run_test() -> None:
                async with httpx.AsyncClient() as client:
                    with (
                        patch(
                            "Screening.full_text_screening.orchestrator.call_with_retry",
                            new=AsyncMock(
                                side_effect=[
                                    SimpleNamespace(status_code=200, json=lambda: {"output_text": "bad output"}),
                                    SimpleNamespace(status_code=200, json=lambda: {"output_text": "still bad"}),
                                ]
                            ),
                        ),
                        patch("Screening.full_text_screening.orchestrator.post_with_auth_fallback", new=AsyncMock()),
                    ):
                        result = await process_single_paper(client, self.runtime, request)
                self.assertEqual(result["decision"], "Error")
                self.assertIn("parse_error", result["evidence"])

            asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
