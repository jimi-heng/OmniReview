import asyncio
import json
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
from Screening.full_text_screening.orchestrator import process_single_paper, run_fulltext
from Screening.full_text_screening.parsing import StructuredOutputError, extract_conclusion, extract_evidence, parse_structured_output
from Screening.full_text_screening.prompts import build_user_prompt, get_system_prompt
from Screening.full_text_screening.runtime import build_payload, coerce_paper, error_result, post_with_auth_fallback


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
        self.assertIn("Population criteria: Age >= 18\nConfirmed diagnosis", normalized.additional_criteria)
        self.assertIn("Additional Criteria: language: English only", normalized.additional_criteria)
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
        self.assertIn("Additional Criteria: English only", prompt)
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

    def test_process_single_paper_success_returns_complete_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((72, 72), "Hello")
                doc.save(pdf_path)

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=9, title="Demo", pdf_path=pdf_path),
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
                                        "output_text": '{"decision":"Included","reason":"Explicit match.","evidence":{"study_design":"","population":"Adults","intervention":"","comparison":"","outcomes":"","extra_rules":""}}'
                                    },
                                )
                            ),
                        ),
                        patch("Screening.full_text_screening.orchestrator.post_with_auth_fallback", new=AsyncMock()),
                    ):
                        result = await process_single_paper(client, self.runtime, request)
                self.assertEqual(result["id"], 9)
                self.assertEqual(result["decision"], "Included")
                self.assertIsNone(result["hl_path"])
                evidence_payload = json.loads(result["evidence"])
                self.assertIn("evidences", evidence_payload)
                self.assertIn("conclusion", evidence_payload)

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

    def test_process_single_paper_missing_file(self) -> None:
        request = FullTextRequest(
            paper=FullTextPaper(paper_id=100, title="Missing", pdf_path=Path("does-not-exist.pdf")),
            pico_dict={"P": "Adults"},
            project_type="PICOS",
            normalized_pico=normalize_pico_input({"P": "Adults"}),
        )

        async def run_test() -> None:
            async with httpx.AsyncClient() as client:
                result = await process_single_paper(client, self.runtime, request)
            evidence = json.loads(result["evidence"])
            self.assertEqual(result["decision"], "Error")
            self.assertEqual(evidence["error_type"], "missing_file")

        asyncio.run(run_test())

    def test_process_single_paper_http_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                doc.new_page()
                doc.save(pdf_path)

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=101, title="HTTP", pdf_path=pdf_path),
                pico_dict={"P": "Adults"},
                project_type="PICOS",
                normalized_pico=normalize_pico_input({"P": "Adults"}),
            )

            async def run_test() -> None:
                async with httpx.AsyncClient() as client:
                    with (
                        patch(
                            "Screening.full_text_screening.orchestrator.call_with_retry",
                            new=AsyncMock(return_value=SimpleNamespace(status_code=500, json=lambda: {"output_text": "x"})),
                        ),
                        patch("Screening.full_text_screening.orchestrator.post_with_auth_fallback", new=AsyncMock()),
                    ):
                        result = await process_single_paper(client, self.runtime, request)
                evidence = json.loads(result["evidence"])
                self.assertEqual(result["decision"], "Error")
                self.assertEqual(evidence["error_type"], "http_error")

            asyncio.run(run_test())

    def test_process_single_paper_runtime_exception_in_input_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n")

            request = FullTextRequest(
                paper=FullTextPaper(paper_id=102, title="Boom", pdf_path=pdf_path),
                pico_dict={"P": "Adults"},
                project_type="PICOS",
                normalized_pico=normalize_pico_input({"P": "Adults"}),
            )

            async def run_test() -> None:
                async with httpx.AsyncClient() as client:
                    with patch("Screening.full_text_screening.orchestrator.load_pdf_bytes", side_effect=RuntimeError("bad read")):
                        result = await process_single_paper(client, self.runtime, request)
                evidence = json.loads(result["evidence"])
                self.assertEqual(result["decision"], "Error")
                self.assertEqual(evidence["error_type"], "input_read_error")

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
                evidence = json.loads(result["evidence"])
                self.assertEqual(evidence["error_type"], "parse_error")
                self.assertEqual(evidence["raw_output"], "still bad")

            asyncio.run(run_test())

    def test_run_fulltext_multiple_papers_all_return_results(self) -> None:
        papers = [
            {"id": 1, "title": "A", "pdf_path": "a.pdf"},
            {"id": 2, "title": "B", "pdf_path": "b.pdf"},
            {"id": 3, "title": "C", "pdf_path": "c.pdf"},
        ]

        async def fake_process(_client, _runtime, request: FullTextRequest):
            return {"id": request.paper.paper_id, "decision": "Included", "evidence": "{}", "hl_path": None}

        async def run_test() -> None:
            with (
                patch.dict(os.environ, {"DMX_API_KEY_1": "k"}, clear=False),
                patch("Screening.full_text_screening.orchestrator.process_single_paper", new=AsyncMock(side_effect=fake_process)),
            ):
                results = await run_fulltext(papers, {"P": "Adults"}, "PICOS", config={"max_concurrency": 3, "enable_highlight": False})
            self.assertEqual([r["id"] for r in results], [1, 2, 3])

        asyncio.run(run_test())


class AuthFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_fallback_retries_with_bearer(self) -> None:
        api_key = "test-key"
        client = SimpleNamespace(
            post=AsyncMock(
                side_effect=[
                    SimpleNamespace(status_code=401),
                    SimpleNamespace(status_code=200),
                ]
            )
        )
        payload = {"model": "x", "input": []}
        resp = await post_with_auth_fallback(client, "https://example.test/responses", api_key, payload, 10.0)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(client.post.call_count, 2)
        self.assertEqual(client.post.call_args_list[0].kwargs["headers"]["Authorization"], api_key)
        self.assertEqual(client.post.call_args_list[1].kwargs["headers"]["Authorization"], f"Bearer {api_key}")


class ParseEdgeCaseTests(unittest.TestCase):
    def test_extracts_json_from_markdown_fences(self) -> None:
        text = """```json
        {
          "decision": "Included",
          "reason": "OK",
          "evidence": {"design": "RCT", "population": "Adults", "intervention": "", "comparators": "placebo", "outcome": ""}
        }
        ```"""
        parsed = parse_structured_output(text)
        self.assertEqual(parsed["decision"], "Included")
        self.assertEqual(parsed["evidence"]["study_design"], "RCT")
        self.assertEqual(parsed["evidence"]["comparison"], "placebo")

    def test_rejects_unknown_decision(self) -> None:
        with self.assertRaises(StructuredOutputError):
            parse_structured_output('{"decision":"Maybe","reason":"?","evidence":{}}')

    def test_fills_missing_reason(self) -> None:
        parsed = parse_structured_output('{"decision":"Excluded","evidence":{}}')
        self.assertEqual(parsed["reason"], "No reason provided.")

    def test_normalizes_evidence_aliases(self) -> None:
        parsed = parse_structured_output(
            '{"decision":"Included","reason":"ok","evidence":{"design":"cohort","comparators":"control","extra":"rule"}}'
        )
        self.assertEqual(parsed["evidence"]["study_design"], "cohort")
        self.assertEqual(parsed["evidence"]["comparison"], "control")
        self.assertEqual(parsed["evidence"]["additional_criteria"], "rule")

    def test_handles_empty_string(self) -> None:
        with self.assertRaises(StructuredOutputError):
            parse_structured_output("")

    def test_handles_no_json(self) -> None:
        with self.assertRaises(StructuredOutputError):
            parse_structured_output("Plain text without JSON")


class PICONormalizerEdgeCaseTests(unittest.TestCase):
    def test_empty_dict(self) -> None:
        pico = normalize_pico_input({})
        self.assertEqual(pico.study_design, "")
        self.assertEqual(pico.population, "")
        self.assertEqual(pico.intervention, "")
        self.assertEqual(pico.comparison, "")
        self.assertEqual(pico.outcomes, "")
        self.assertEqual(pico.additional_criteria, "")

    def test_alternative_aliases(self) -> None:
        pico = normalize_pico_input(
            {
                "patients": "Adults",
                "exposure": "Smoking",
                "comparators": "Never smokers",
                "endpoint": "Mortality",
            }
        )
        self.assertEqual(pico.population, "Adults")
        self.assertEqual(pico.intervention, "Smoking")
        self.assertEqual(pico.comparison, "Never smokers")
        self.assertEqual(pico.outcomes, "Mortality")

    def test_deeply_nested_flatten(self) -> None:
        pico = normalize_pico_input({"population": {"Age": ["18-65", {"Mean": "50"}], "Setting": {"Site": "Clinic"}}})
        self.assertIn("Age:", pico.population)
        self.assertIn("18-65", pico.population)
        self.assertIn("Mean:", pico.population)
        self.assertIn("Setting:", pico.population)


class PromptGenerationTests(unittest.TestCase):
    def test_get_system_prompt_picos(self) -> None:
        prompt = get_system_prompt("PICOS")
        self.assertIn("SPIC components", prompt)
        self.assertIn('decision = "Included"', prompt)
        self.assertIn("STRICT OUTPUT FORMAT", prompt)

    def test_get_system_prompt_peco(self) -> None:
        prompt = get_system_prompt("PECO")
        self.assertIn("Exposure (E)", prompt)
        self.assertIn('decision = "Included"', prompt)
        self.assertIn("STRICT OUTPUT FORMAT", prompt)

    def test_get_system_prompt_piro(self) -> None:
        prompt = get_system_prompt("PIRO")
        self.assertIn("Indicator (I)", prompt)
        self.assertIn("Reference (R)", prompt)
        self.assertIn('decision = "Included"', prompt)
        self.assertIn("STRICT OUTPUT FORMAT", prompt)

    def test_build_user_prompt_piro_fields(self) -> None:
        request = FullTextRequest(
            paper=FullTextPaper(paper_id=1, title="Demo", pdf_path=Path("demo.pdf")),
            pico_dict={"population": "Adults", "indicator": "BP", "reference": "placebo"},
            project_type="PIRO",
            normalized_pico=normalize_pico_input({"population": "Adults", "indicator": "BP", "reference": "placebo"}),
        )
        prompt = build_user_prompt(request)
        self.assertIn("Indicator:", prompt)
        self.assertIn("Reference:", prompt)


class RuntimeEdgeCaseTests(unittest.TestCase):
    def test_resolve_config_with_none(self) -> None:
        with patch.dict(os.environ, {"DMX_API_KEY_1": "k"}, clear=False):
            runtime = resolve_runtime_config(None, parse_pages_spec=parse_pages_spec)
        self.assertEqual(runtime.api_key, "k")
        self.assertTrue(runtime.endpoint.endswith("/responses"))

    def test_resolve_config_missing_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                resolve_runtime_config(None, parse_pages_spec=parse_pages_spec)

    def test_build_payload_raises_without_content(self) -> None:
        with self.assertRaises(ValueError):
            build_payload("gpt-4.1", prompt="hi")

    def test_coerce_paper_from_dict(self) -> None:
        paper = coerce_paper({"id": 7, "pdf_path": "a.pdf", "title": "T"})
        self.assertEqual(paper.paper_id, 7)
        self.assertEqual(paper.title, "T")
        self.assertEqual(paper.pdf_path, Path("a.pdf"))

    def test_coerce_paper_missing_path(self) -> None:
        with self.assertRaises(KeyError):
            coerce_paper({"id": 1, "title": "T"})

    def test_error_result_includes_raw_output(self) -> None:
        result = error_result(1, error_type="parse_error", message="bad", raw_output="RAW")
        evidence = json.loads(result["evidence"])
        self.assertEqual(evidence["error_type"], "parse_error")
        self.assertEqual(evidence["raw_output"], "RAW")


if __name__ == "__main__":
    unittest.main()
