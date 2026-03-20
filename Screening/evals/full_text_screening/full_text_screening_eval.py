#!/usr/bin/env python3
"""
Full text screening evaluation wrapper.

This script mirrors the frontend call to `Screening.FullTextScreening.run_fulltext_ai_sync`
while using the local eval datasets under `Screening/evals/full_text_screening/datasets/`.

It:
1) Loads the PICO-style input from `PICO15.json` (similar to user input).
2) Screens the PDFs under `datasets/pdf/` via `run_fulltext_ai_sync`.
3) Compares predicted decisions with the reference labels in
   `PICO15_FullTextAssessment.csv`, and prints summary metrics.
4) Writes a timestamped per-paper results CSV under `outputs/`.

Examples:
  python Screening/evals/full_text_screening/full_text_screening_eval.py
  python Screening/evals/full_text_screening/full_text_screening_eval.py --model gpt-4.1 --max-concurrency 3
  python Screening/evals/full_text_screening/full_text_screening_eval.py --pico-json '{"s":"RCT","p":"adults","i":"drug","c":"placebo","o":""}'
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


EVAL_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EVAL_DIR / "datasets"
PDF_DIR = DATASETS_DIR / "pdf"
PICO_JSON_PATH = DATASETS_DIR / "PICO15.json"
REFERENCE_CSV_PATH = DATASETS_DIR / "PICO15_FullTextAssessment.csv"
OUTPUTS_DIR = EVAL_DIR / "outputs"


ROOT_DIR = EVAL_DIR.parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Screening.FullTextScreening import run_fulltext_ai_sync  # noqa: E402


def _normalize_label(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"include", "included", "1", "yes", "y", "true"}:
        return "Included"
    if normalized in {"exclude", "excluded", "0", "no", "n", "false"}:
        return "Excluded"
    if not normalized:
        return ""
    return value.strip()


def _format_ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{(numerator / denominator) * 100:.2f}%"


def _safe_int(text: str) -> Optional[int]:
    try:
        return int(text)
    except Exception:
        return None


def _join_maybe_list(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    return str(value)


def _flatten_outcome(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    if isinstance(value, Mapping):
        parts: list[str] = []
        for category, items in value.items():
            if isinstance(items, list):
                joined = ", ".join(str(item) for item in items if str(item).strip())
                if joined:
                    parts.append(f"{category}: {joined}")
            else:
                item_text = str(items).strip()
                if item_text:
                    parts.append(f"{category}: {item_text}")
        return "; ".join(parts)
    return str(value)


def _flatten_extra(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(parts)
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            key_text = str(key).strip()
            item_text = str(item).strip()
            if key_text and item_text:
                parts.append(f"{key_text}: {item_text}")
            elif item_text:
                parts.append(item_text)
        return "\n".join(parts)
    return str(value).strip()


def load_pico_payload(path: Path) -> dict[str, str]:
    """Load `datasets/PICO15.json` and normalize it into the frontend payload shape."""

    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, Mapping):
        raise ValueError(f"PICO JSON must be an object or a non-empty list of objects: {path}")

    return {
        "s": str(data.get("S", "") or ""),
        "p": str(data.get("P", "") or ""),
        "i": str(data.get("I", "") or ""),
        "c": _join_maybe_list(data.get("C", "")),
        "o": _flatten_outcome(data.get("O", "")),
        "es": _flatten_extra(data.get("ES", data.get("es", ""))),
    }


def _parse_pico_json(value: str) -> dict[str, str]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise ValueError("--pico-json must decode to a JSON object")
    return {str(key): "" if item is None else str(item) for key, item in parsed.items()}


def load_reference_labels(path: Path) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Reference CSV has no header row: {path}")

        # Be tolerant to BOM / slight header drift.
        index_field = next((name for name in reader.fieldnames if name and name.endswith("Paper_Index")), None)
        label_field = next(
            (name for name in reader.fieldnames if name and name.endswith("Full-text_Assessment")),
            None,
        )
        if not index_field or not label_field:
            raise ValueError(f"Reference CSV must include Paper_Index and Full-text_Assessment columns: {path}")

        labels: dict[str, str] = {}
        for row in reader:
            idx = (row.get(index_field) or "").strip()
            label = _normalize_label(row.get(label_field) or "")
            if idx:
                labels[idx] = label
        return labels


def discover_eval_pdfs(pdf_dir: Path) -> list[Path]:
    pdfs = [path for path in pdf_dir.glob("*.pdf") if path.is_file()]

    def sort_key(path: Path):
        num = _safe_int(path.stem)
        return (0, num) if num is not None else (1, path.stem.lower())

    return sorted(pdfs, key=sort_key)


def build_papers_for_frontend(pdfs: Iterable[Path]) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    for pdf_path in pdfs:
        paper_id = _safe_int(pdf_path.stem)
        if paper_id is None:
            print(f"Skipping non-numeric PDF stem (cannot map to int paper id): {pdf_path.name}")
            continue
        papers.append({"id": paper_id, "title": pdf_path.stem, "pdf_path": str(pdf_path.resolve())})
    return papers


@dataclass(frozen=True)
class EvalRow:
    paper_index: str
    reference: str
    predicted: str
    correct: bool
    is_error: bool
    evidence: str
    highlight_path: str
    pdf_path: str


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate full-text screening on the local PICO15 dataset (mirrors frontend logic).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pdf-dir", type=Path, default=PDF_DIR, help="Directory containing evaluation PDFs.")
    parser.add_argument("--pico-json-path", type=Path, default=PICO_JSON_PATH, help="Path to the eval PICO15 JSON.")
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help="Optional frontend-style PICO JSON string (overrides --pico-json-path).",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=REFERENCE_CSV_PATH,
        help="Reference label CSV (Paper_Index -> Full-text_Assessment).",
    )
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR, help="Directory for timestamped outputs.")
    parser.add_argument(
        "--project-type",
        type=str,
        default="PICOS",
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="Project type to pass through to the screening runtime.",
    )

    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1", help="API base URL")
    parser.add_argument("--model", type=str, default="gpt-4.1", help="Model name to use")
    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1", help="Environment variable name for API key")
    parser.add_argument(
        "--pdf-pages",
        type=str,
        default="all",
        help="Pages to process: 'all' or '1-3,5' (requires pymupdf for slicing).",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="API timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Number of retry attempts on failure")
    parser.add_argument("--retry-delay", type=float, default=3.0, help="Delay between retries in seconds")
    parser.add_argument("--max-concurrency", type=int, default=5, help="Maximum concurrent API requests")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of PDFs to evaluate (0 = all).")
    return parser


def write_eval_csv(path: Path, rows: list[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "Paper_Index",
        "Reference",
        "Predicted",
        "Correct",
        "IsError",
        "Evidence",
        "HighlightPath",
        "PdfPath",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "Paper_Index": row.paper_index,
                    "Reference": row.reference,
                    "Predicted": row.predicted,
                    "Correct": "1" if row.correct else "0",
                    "IsError": "1" if row.is_error else "0",
                    "Evidence": row.evidence,
                    "HighlightPath": row.highlight_path,
                    "PdfPath": row.pdf_path,
                }
            )


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    if not args.pdf_dir.exists():
        print(f"Error: pdf directory not found: {args.pdf_dir}")
        sys.exit(1)
    if not args.reference_csv.exists():
        print(f"Error: reference CSV not found: {args.reference_csv}")
        sys.exit(1)
    if not args.pico_json and not args.pico_json_path.exists():
        print(f"Error: eval PICO JSON not found: {args.pico_json_path}")
        sys.exit(1)

    pdf_paths = discover_eval_pdfs(args.pdf_dir)
    if args.limit and args.limit > 0:
        pdf_paths = pdf_paths[: int(args.limit)]
    if not pdf_paths:
        print(f"Error: no PDF files found in: {args.pdf_dir}")
        sys.exit(1)

    reference = load_reference_labels(args.reference_csv)

    if args.pico_json:
        pico_payload = _parse_pico_json(args.pico_json)
    else:
        pico_payload = load_pico_payload(args.pico_json_path)

    papers = build_papers_for_frontend(pdf_paths)
    if not papers:
        print("Error: no valid papers to evaluate (all PDF stems were non-numeric).")
        sys.exit(1)

    paper_indices = [str(p["id"]) for p in papers]
    missing_ref = [idx for idx in paper_indices if idx not in reference]
    if missing_ref:
        print(f"Warning: {len(missing_ref)} PDFs have no reference labels and will be skipped: {missing_ref[:10]}")

    papers = [paper for paper in papers if str(paper["id"]) in reference]
    if not papers:
        print("Error: none of the PDFs have reference labels.")
        sys.exit(1)

    print("=" * 60)
    print("Full Text Screening Evaluation (PICO15)")
    print("=" * 60)
    print(f"PDF dir:          {args.pdf_dir}")
    print(f"PDF count:        {len(papers)}")
    print(f"Reference CSV:    {args.reference_csv}")
    print(f"Project type:     {args.project_type}")
    print(f"PICO payload:     {json.dumps(pico_payload, ensure_ascii=False)}")
    print(f"Model:            {args.model}")
    print(f"Base URL:         {args.base_url}")
    print(f"API key env var:  {args.api_key_env}")
    print(f"PDF pages:        {args.pdf_pages}")
    print(f"Max concurrency:  {args.max_concurrency}")
    print("=" * 60)
    print()

    os.environ.setdefault("PYTHONUTF8", "1")

    try:
        results = run_fulltext_ai_sync(
            papers,
            pico_payload,
            str(args.project_type),
            config={
                "base_url": str(args.base_url),
                "model": str(args.model),
                "api_key_env": str(args.api_key_env),
                "pdf_pages": str(args.pdf_pages),
                "timeout": float(args.timeout),
                "retries": int(args.retries),
                "retry_delay": float(args.retry_delay),
                "max_concurrency": int(args.max_concurrency),
                "enable_highlight": False,
            },
        )
    except RuntimeError as exc:
        message = str(exc)
        if "Missing env var" in message:
            print("Error: missing API key configuration.")
            print(message)
            print(f"Fix: set `{args.api_key_env}` in `Screening/.env` (or in your shell env) and retry.")
            sys.exit(1)
        raise

    predicted_by_id: dict[str, dict[str, Any]] = {str(item.get("id")): item for item in results}

    rows: list[EvalRow] = []
    for paper in papers:
        pid = str(paper["id"])
        ref = _normalize_label(reference.get(pid, ""))
        result = predicted_by_id.get(pid) or {}
        pred = _normalize_label(str(result.get("decision") or ""))
        is_error = pred == "Error" or not pred
        correct = (pred == ref) and (not is_error) and (ref in {"Included", "Excluded"})
        rows.append(
            EvalRow(
                paper_index=pid,
                reference=ref,
                predicted=pred,
                correct=correct,
                is_error=is_error,
                evidence=str(result.get("evidence") or ""),
                highlight_path=str(result.get("hl_path") or ""),
                pdf_path=str(paper.get("pdf_path") or ""),
            )
        )

    total = len(rows)
    errors = sum(1 for row in rows if row.is_error)
    correct = sum(1 for row in rows if row.correct)
    accuracy = _format_ratio(correct, total)

    non_error_rows = [row for row in rows if not row.is_error]
    non_error_total = len(non_error_rows)
    non_error_correct = sum(1 for row in non_error_rows if row.correct)
    accuracy_no_error = _format_ratio(non_error_correct, non_error_total)

    tp = sum(1 for row in rows if row.predicted == "Included" and row.reference == "Included")
    tn = sum(1 for row in rows if row.predicted == "Excluded" and row.reference == "Excluded")
    fp = sum(1 for row in rows if row.predicted == "Included" and row.reference == "Excluded")
    fn = sum(1 for row in rows if row.predicted == "Excluded" and row.reference == "Included")

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    args.outputs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = args.outputs_dir / f"eval_full_text_{timestamp}.csv"
    write_eval_csv(output_csv, rows)

    wrong = [row for row in rows if (not row.correct) and (not row.is_error)]
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total papers:                 {total}")
    print(f"Errors:                       {errors} ({_format_ratio(errors, total)})")
    print(f"Correct (incl. errors):       {correct} ({accuracy})")
    print(f"Correct (excluding errors):   {non_error_correct}/{non_error_total} ({accuracy_no_error})")
    print()
    print("Confusion matrix (Included as positive):")
    print(f"  TP: {tp}  FP: {fp}")
    print(f"  FN: {fn}  TN: {tn}")
    print(f"  Precision: {precision:.3f}  Recall: {recall:.3f}  F1: {f1:.3f}")
    print()
    print(f"Output CSV: {output_csv}")

    if wrong:
        print("\nMisclassified (first 15):")
        for row in wrong[:15]:
            print(f"  {row.paper_index}: ref={row.reference} pred={row.predicted}")


if __name__ == "__main__":
    main()
