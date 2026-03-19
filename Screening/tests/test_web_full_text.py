import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parents[2]
SCREENING_DIR = ROOT_DIR / "Screening"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SCREENING_DIR) not in sys.path:
    sys.path.insert(0, str(SCREENING_DIR))

import fitz

from Screening.WebFullText import (
    _load_pdf_bytes,
    _parse_pages_spec,
    _resolve_runtime_config,
)


class WebFullTextTests(unittest.TestCase):
    def test_parse_pages_spec_supports_ranges(self) -> None:
        self.assertIsNone(_parse_pages_spec("all"))
        self.assertEqual(_parse_pages_spec("1-3,5"), [1, 2, 3, 5])
        self.assertEqual(_parse_pages_spec("5,3-1"), [1, 2, 3, 5])

    def test_load_pdf_bytes_slices_selected_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "sample.pdf"
            with fitz.open() as doc:
                for idx in range(3):
                    page = doc.new_page()
                    page.insert_text((72, 72), f"Page {idx + 1}")
                doc.save(pdf_path)

            sliced_bytes = _load_pdf_bytes(pdf_path, [1, 3])
            with fitz.open(stream=sliced_bytes, filetype="pdf") as sliced:
                self.assertEqual(sliced.page_count, 2)

    def test_resolve_runtime_config_merges_env_and_mapping(self) -> None:
        env = {
            "DMX_API_KEY_1": "test-key",
            "WEB_FULLTEXT_MODEL": "gpt-from-env",
            "WEB_FULLTEXT_TIMEOUT": "120",
        }
        with patch.dict(os.environ, env, clear=False):
            runtime = _resolve_runtime_config({"max_concurrency": 9, "pdf_pages": "2-4"})

        self.assertEqual(runtime.api_key, "test-key")
        self.assertEqual(runtime.model, "gpt-from-env")
        self.assertEqual(runtime.timeout, 120.0)
        self.assertEqual(runtime.max_concurrency, 9)
        self.assertEqual(runtime.selected_pages, [2, 3, 4])


if __name__ == "__main__":
    unittest.main()
