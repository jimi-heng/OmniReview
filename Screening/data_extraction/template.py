from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from openpyxl import load_workbook


METADATA_FIELDS = {"Rayyan_ID", "Title", "Abstract", "Full_Text", "Extractor", "Checker"}


def read_template_columns(template_path: Path) -> Tuple[List[str], List[str]]:
    """Read column names from all sheets in an Excel template."""
    wb = load_workbook(template_path, read_only=True)
    try:
        all_columns: List[str] = []
        seen: set[str] = set()

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
            if not header_row:
                continue
            for value in header_row:
                if value is None:
                    continue
                col = str(value).strip()
                if col and col not in seen:
                    seen.add(col)
                    all_columns.append(col)

        if not all_columns:
            raise ValueError("No columns found in any sheet")

        llm_columns = [c for c in all_columns if c not in METADATA_FIELDS]
        return all_columns, llm_columns
    finally:
        wb.close()

