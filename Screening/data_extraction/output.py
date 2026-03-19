from __future__ import annotations

import asyncio
import csv
from pathlib import Path
from typing import List

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from .template import METADATA_FIELDS, read_template_columns


async def csv_writer(queue: asyncio.Queue, output_csv: Path, columns: List[str]) -> None:
    fieldnames = ["ID", "Title", "RelativePath"] + columns + ["Error"]
    with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        f.flush()

        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                writer.writerow(item)
                f.flush()
            finally:
                queue.task_done()


def csv_to_excel(csv_path: Path, xlsx_path: Path, template_path: Path) -> None:
    template_columns, _ = read_template_columns(template_path)
    preferred = ["ID", "Title", "RelativePath"] + [c for c in template_columns if c not in METADATA_FIELDS] + ["Error"]

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        csv_headers = list(reader.fieldnames or [])
        ordered_headers = [h for h in preferred if h in csv_headers]
        ordered_headers.extend([h for h in csv_headers if h not in ordered_headers])

        wb = Workbook()
        ws = wb.active
        ws.title = "baseline characteristics"
        ws.append(ordered_headers)
        for row in reader:
            ws.append([ILLEGAL_CHARACTERS_RE.sub("", row.get(col, "")) for col in ordered_headers])

    xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(xlsx_path)

