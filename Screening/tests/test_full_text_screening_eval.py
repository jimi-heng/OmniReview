import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from Screening.evals.full_text_screening.full_text_screening_eval import (
    DATASET_PRESETS,
    build_eval_papers,
    discover_eval_inputs,
    resolve_dataset_config,
)


class FullTextScreeningEvalTests(unittest.TestCase):
    def test_resolve_dataset_config_uses_preset_defaults(self) -> None:
        config = resolve_dataset_config(
            Namespace(
                dataset="cd006748",
                inputs_dir=None,
                pico_json_path=None,
                reference_csv=None,
                project_type=None,
            )
        )

        self.assertEqual(config.key, "cd006748")
        self.assertEqual(config.label, "CD006748")
        self.assertEqual(config.inputs_dir, DATASET_PRESETS["cd006748"].inputs_dir.resolve())
        self.assertEqual(config.project_type, "PICOS")

    def test_discover_eval_inputs_supports_pdf_and_txt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            inputs_dir = Path(temp_dir)
            (inputs_dir / "b.txt").write_text("hello", encoding="utf-8")
            (inputs_dir / "2.pdf").write_bytes(b"%PDF-1.4\n")
            (inputs_dir / "notes.md").write_text("ignore", encoding="utf-8")

            discovered = discover_eval_inputs(inputs_dir)

            self.assertEqual([path.name for path in discovered], ["2.pdf", "b.txt"])

    def test_build_eval_papers_assigns_numeric_runtime_ids_and_string_indices(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "CD006748-bib-0030.txt"
            txt_path.write_text("hello", encoding="utf-8")

            papers = build_eval_papers([txt_path])

            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0].paper_id, 1)
            self.assertEqual(papers[0].paper_index, "CD006748-bib-0030")
            self.assertEqual(papers[0].as_runtime_paper()["pdf_path"], str(txt_path.resolve()))


if __name__ == "__main__":
    unittest.main()
