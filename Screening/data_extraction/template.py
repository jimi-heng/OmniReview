from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from openpyxl import load_workbook


METADATA_FIELDS = {"Rayyan_ID", "Title", "Abstract", "Full_Text", "Extractor", "Checker"}


@dataclass(frozen=True)
class TemplateColumns:
    all_columns: List[str]
    llm_columns: List[str]
    descriptions: Dict[str, str]


def read_template_columns(template_path: Path) -> TemplateColumns:
    """Read template headers plus optional second-row descriptions from all sheets."""
    wb = load_workbook(template_path, read_only=True)
    try:
        all_columns: List[str] = []
        seen: set[str] = set()
        descriptions: Dict[str, str] = {}

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(min_row=1, max_row=2, values_only=True))
            header_row = rows[0] if rows else None
            description_row = rows[1] if len(rows) > 1 else ()
            if not header_row:
                continue
            for index, value in enumerate(header_row):
                if value is None:
                    continue
                col = str(value).strip()
                description = ""
                if index < len(description_row):
                    raw_description = description_row[index]
                    if raw_description is not None:
                        description = str(raw_description).strip()
                if col and col not in seen:
                    seen.add(col)
                    all_columns.append(col)
                    descriptions[col] = description
                elif col and description and not descriptions.get(col):
                    descriptions[col] = description

        if not all_columns:
            raise ValueError("No columns found in any sheet")

        llm_columns = [c for c in all_columns if c not in METADATA_FIELDS]
        llm_descriptions = {column: descriptions.get(column, "") for column in llm_columns}
        return TemplateColumns(all_columns=all_columns, llm_columns=llm_columns, descriptions=llm_descriptions)
    finally:
        wb.close()

