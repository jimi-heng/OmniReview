#!/usr/bin/env python3
"""
Full text screening evaluation wrapper.

This script mirrors the frontend call to `Screening.FullTextScreening.run_fulltext_ai_sync`
while using local datasets under `Screening/evals/full_text_screening/datasets/`.

It:
1) Loads the PICO-style input for a selected dataset preset.
2) Screens the dataset's PDF or TXT full-text inputs via `run_fulltext_ai_sync`.
3) Compares predicted decisions with the reference labels.
4) Writes a timestamped per-paper results CSV under `outputs/`.

Examples:
  python Screening/evals/full_text_screening/full_text_screening_eval.py
  python Screening/evals/full_text_screening/full_text_screening_eval.py --dataset cd006748
  python Screening/evals/full_text_screening/full_text_screening_eval.py --dataset cd008873
  python Screening/evals/full_text_screening/full_text_screening_eval.py --dataset cd010912
  python Screening/evals/full_text_screening/full_text_screening_eval.py --dataset pico15 --model gpt-4.1 --max-concurrency 3
  python Screening/evals/full_text_screening/full_text_screening_eval.py --dataset cd006748 --inputs-dir Screening/evals/full_text_screening/datasets/CD006748/text
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional


EVAL_DIR = Path(__file__).resolve().parent
DATASETS_DIR = EVAL_DIR / "datasets"
OUTPUTS_DIR = EVAL_DIR / "outputs"
SUPPORTED_INPUT_SUFFIXES = {".pdf", ".txt"}


ROOT_DIR = EVAL_DIR.parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from Screening.FullTextScreening import run_fulltext_ai_sync  # noqa: E402
from Screening.full_text_screening.pico_normalizer import coerce_pico_payload  # noqa: E402


@dataclass(frozen=True)
class EvalDatasetPreset:
    key: str
    label: str
    inputs_dir: Path
    pico_json_path: Path
    reference_csv_path: Path
    project_type: str = "PICOS"


@dataclass(frozen=True)
class EvalDatasetConfig:
    key: str
    label: str
    inputs_dir: Path
    pico_json_path: Path
    reference_csv_path: Path
    project_type: str


@dataclass(frozen=True)
class EvalPaper:
    paper_id: int
    paper_index: str
    title: str
    source_path: Path

    def as_runtime_paper(self) -> dict[str, Any]:
        return {
            "id": self.paper_id,
            "title": self.title,
            "pdf_path": str(self.source_path),
        }


@dataclass(frozen=True)
class EvalRow:
    paper_index: str
    reference: str
    predicted: str
    correct: bool
    is_error: bool
    evidence: str
    highlight_path: str
    source_path: str


DATASET_PRESETS: dict[str, EvalDatasetPreset] = {
    "pico15": EvalDatasetPreset(
        key="pico15",
        label="PICO15",
        inputs_dir=DATASETS_DIR / "PICO15" / "pdf",
        pico_json_path=DATASETS_DIR / "PICO15" / "PICO15.json",
        reference_csv_path=DATASETS_DIR / "PICO15" / "PICO15_FullTextAssessment.csv",
        project_type="PICOS",
    ),
    "cd006748": EvalDatasetPreset(
        key="cd006748",
        label="CD006748",
        inputs_dir=DATASETS_DIR / "CD006748" / "text",
        pico_json_path=DATASETS_DIR / "CD006748" / "PICO6748.json",
        reference_csv_path=DATASETS_DIR / "CD006748" / "PICO6748_FullTextAssessment.csv",
        project_type="PICOS",
    ),
    "cd008873": EvalDatasetPreset(
        key="cd008873",
        label="CD008873",
        inputs_dir=DATASETS_DIR / "CD008873" / "text",
        pico_json_path=DATASETS_DIR / "CD008873" / "PICO8873.json",
        reference_csv_path=DATASETS_DIR / "CD008873" / "CD008873_FullTextAssessment.csv",
        project_type="PICOS",
    ),
    "cd010912": EvalDatasetPreset(
        key="cd010912",
        label="CD010912",
        inputs_dir=DATASETS_DIR / "CD010912" / "text",
        pico_json_path=DATASETS_DIR / "CD010912" / "PICO010912.json",
        reference_csv_path=DATASETS_DIR / "CD010912" / "CD010912_FullTextAssessment.csv",
        project_type="PICOS",
    ),
}


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


def _sort_key(path: Path) -> tuple[int, Any, str]:
    numeric_stem = _safe_int(path.stem)
    if numeric_stem is not None:
        return (0, numeric_stem, path.suffix.lower())
    return (1, path.stem.lower(), path.suffix.lower())


def load_pico_payload(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    try:
        return coerce_pico_payload(data)
    except TypeError as exc:
        raise ValueError(f"PICO JSON must be an object or a non-empty list of objects: {path}") from exc


def _parse_pico_json(value: str) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    try:
        return coerce_pico_payload(parsed)
    except TypeError as exc:
        raise ValueError(f"--pico-json {exc}") from exc


def load_reference_labels(path: Path) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Reference CSV has no header row: {path}")

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


def discover_eval_inputs(inputs_dir: Path) -> list[Path]:
    inputs = [
        path
        for path in inputs_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
    ]
    return sorted(inputs, key=_sort_key)


def build_eval_papers(paths: Iterable[Path]) -> list[EvalPaper]:
    papers: list[EvalPaper] = []
    for paper_id, source_path in enumerate(paths, start=1):
        resolved = source_path.resolve()
        papers.append(
            EvalPaper(
                paper_id=paper_id,
                paper_index=resolved.stem,
                title=resolved.stem,
                source_path=resolved,
            )
        )
    return papers


def resolve_dataset_config(args: argparse.Namespace) -> EvalDatasetConfig:
    preset = DATASET_PRESETS[args.dataset]
    inputs_dir = Path(args.inputs_dir).resolve() if args.inputs_dir else preset.inputs_dir.resolve()
    pico_json_path = Path(args.pico_json_path).resolve() if args.pico_json_path else preset.pico_json_path.resolve()
    reference_csv_path = Path(args.reference_csv).resolve() if args.reference_csv else preset.reference_csv_path.resolve()
    project_type = str(args.project_type or preset.project_type)
    return EvalDatasetConfig(
        key=preset.key,
        label=preset.label,
        inputs_dir=inputs_dir,
        pico_json_path=pico_json_path,
        reference_csv_path=reference_csv_path,
        project_type=project_type,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate full-text screening on local preset datasets (PDF or TXT).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default="pico15",
        choices=sorted(DATASET_PRESETS),
        help="Dataset preset to evaluate.",
    )
    parser.add_argument(
        "--inputs-dir",
        "--pdf-dir",
        dest="inputs_dir",
        type=Path,
        default=None,
        help="Directory containing evaluation inputs (.pdf or .txt). Overrides the dataset preset path.",
    )
    parser.add_argument(
        "--pico-json-path",
        type=Path,
        default=None,
        help="Path to the dataset PICO JSON. Overrides the dataset preset path.",
    )
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help="Optional frontend-style PICO JSON string (overrides --pico-json-path).",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=None,
        help="Reference label CSV. Overrides the dataset preset path.",
    )
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUTS_DIR, help="Directory for timestamped outputs.")
    parser.add_argument(
        "--project-type",
        type=str,
        default=None,
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="Project type to pass through to the screening runtime. Defaults to the dataset preset value.",
    )
    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1", help="API base URL")
    parser.add_argument("--model", type=str, default="gpt-4.1", help="Model name to use")
    parser.add_argument("--api-key-env", type=str, default="DMX_API_KEY_1", help="Environment variable name for API key")
    parser.add_argument(
        "--pdf-pages",
        type=str,
        default="all",
        help="Pages to process for PDF inputs: 'all' or '1-3,5' (requires pymupdf for slicing).",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="API timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Number of retry attempts on failure")
    parser.add_argument("--retry-delay", type=float, default=3.0, help="Delay between retries in seconds")
    parser.add_argument("--max-concurrency", type=int, default=10, help="Maximum concurrent API requests")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on number of inputs to evaluate (0 = all).")
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="Print available dataset presets and exit.",
    )
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
        "SourcePath",
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
                    "SourcePath": row.source_path,
                }
            )


def _print_available_datasets() -> None:
    print("Available datasets:")
    for key in sorted(DATASET_PRESETS):
        preset = DATASET_PRESETS[key]
        print(f"- {preset.key}: {preset.label}")
        print(f"  inputs:    {preset.inputs_dir}")
        print(f"  pico json: {preset.pico_json_path}")
        print(f"  labels:    {preset.reference_csv_path}")


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_datasets:
        _print_available_datasets()
        return

    dataset = resolve_dataset_config(args)

    if not dataset.inputs_dir.exists():
        print(f"Error: input directory not found: {dataset.inputs_dir}")
        sys.exit(1)
    if not dataset.reference_csv_path.exists():
        print(f"Error: reference CSV not found: {dataset.reference_csv_path}")
        sys.exit(1)
    if not args.pico_json and not dataset.pico_json_path.exists():
        print(f"Error: eval PICO JSON not found: {dataset.pico_json_path}")
        sys.exit(1)

    input_paths = discover_eval_inputs(dataset.inputs_dir)
    if args.limit and args.limit > 0:
        input_paths = input_paths[: int(args.limit)]
    if not input_paths:
        print(f"Error: no .pdf or .txt files found in: {dataset.inputs_dir}")
        sys.exit(1)

    reference = load_reference_labels(dataset.reference_csv_path)

    if args.pico_json:
        pico_payload = _parse_pico_json(args.pico_json)
    else:
        pico_payload = load_pico_payload(dataset.pico_json_path)

    papers = build_eval_papers(input_paths)
    paper_indices = [paper.paper_index for paper in papers]
    missing_ref = [paper_index for paper_index in paper_indices if paper_index not in reference]
    if missing_ref:
        print(f"Warning: {len(missing_ref)} inputs have no reference labels and will be skipped: {missing_ref[:10]}")

    papers = [paper for paper in papers if paper.paper_index in reference]
    if not papers:
        print("Error: none of the discovered inputs have reference labels.")
        sys.exit(1)

    runtime_papers = [paper.as_runtime_paper() for paper in papers]

    print("=" * 60)
    print(f"Full Text Screening Evaluation ({dataset.label})")
    print("=" * 60)
    print(f"Dataset preset:    {dataset.key}")
    print(f"Inputs dir:        {dataset.inputs_dir}")
    print(f"Input count:       {len(runtime_papers)}")
    print(f"Reference CSV:     {dataset.reference_csv_path}")
    print(f"Project type:      {dataset.project_type}")
    print(f"PICO payload:      {json.dumps(pico_payload, ensure_ascii=False)}")
    print(f"Model:             {args.model}")
    print(f"Base URL:          {args.base_url}")
    print(f"API key env var:   {args.api_key_env}")
    print(f"PDF pages:         {args.pdf_pages}")
    print(f"Max concurrency:   {args.max_concurrency}")
    print("=" * 60)
    print()

    os.environ.setdefault("PYTHONUTF8", "1")

    try:
        results = run_fulltext_ai_sync(
            runtime_papers,
            pico_payload,
            dataset.project_type,
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
        ref = _normalize_label(reference.get(paper.paper_index, ""))
        result = predicted_by_id.get(str(paper.paper_id)) or {}
        pred = _normalize_label(str(result.get("decision") or ""))
        is_error = pred == "Error" or not pred
        correct = (pred == ref) and (not is_error) and (ref in {"Included", "Excluded"})
        rows.append(
            EvalRow(
                paper_index=paper.paper_index,
                reference=ref,
                predicted=pred,
                correct=correct,
                is_error=is_error,
                evidence=str(result.get("evidence") or ""),
                highlight_path=str(result.get("hl_path") or ""),
                source_path=str(paper.source_path),
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
    output_csv = args.outputs_dir / f"eval_full_text_{dataset.key}_{timestamp}.csv"
    write_eval_csv(output_csv, rows)

    wrong = [row for row in rows if (not row.correct) and (not row.is_error)]
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Total inputs:                 {total}")
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
    start = time.perf_counter()
    try:
        main()
    finally:
        print(f"\nElapsed: {time.perf_counter() - start:.2f}s")
