#!/usr/bin/env python3
"""
Data extraction evaluation wrapper.

This script mirrors the frontend subprocess call to
`Screening/EnhancedDataExtraction.py` while using the local eval datasets and
template files under `Screening/evals/data_extraction/datasets/`.

Examples:
    python data_extraction_eval.py
    python data_extraction_eval.py --pipeline-mode legacy
    python data_extraction_eval.py --pipeline-mode phase1
    python data_extraction_eval.py --pipeline-mode phase2
    python data_extraction_eval.py --pico-json '{"s":"RCT","p":"children","i":"iron","c":"placebo","o":"hemoglobin"}'
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


EVAL_DIR = Path(__file__).resolve().parent
SCREENING_DIR = EVAL_DIR.parent.parent

DATASETS_DIR = EVAL_DIR / "datasets" / "pdf"
TEMPLATE_PATH = EVAL_DIR / "datasets" / "Template_PICO6.xlsx"
PICO_JSON_PATH = EVAL_DIR / "datasets" / "PICO6.json"
OUTPUTS_DIR = EVAL_DIR / "outputs"
REFERENCE_XLSX = EVAL_DIR / "PICO6.xlsx"
EXTRACTION_SCRIPT = SCREENING_DIR / "EnhancedDataExtraction.py"


def load_pico_from_json(path: Path) -> dict[str, str]:
    """Load the eval PICO JSON and normalize it into the frontend payload shape."""

    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    outcome = data.get("O", "")
    if isinstance(outcome, dict):
        parts: list[str] = []
        for category, items in outcome.items():
            if isinstance(items, list):
                parts.append(f"{category}: {', '.join(str(item) for item in items)}")
            else:
                parts.append(f"{category}: {items}")
        outcome = "; ".join(parts)

    return {
        "s": str(data.get("S", "")),
        "p": str(data.get("P", "")),
        "i": str(data.get("I", "")),
        "c": str(data.get("C", "")),
        "o": str(outcome),
        "es": "",
    }


def build_command(
    *,
    python_exe: str,
    resources_dir: Path,
    template: Path,
    output_csv: Path,
    output_xlsx: Path,
    project_type: str,
    pico_json_str: str,
    pipeline_mode: str,
) -> list[str]:
    """Build the subprocess command used to invoke the stable extraction facade."""

    return [
        python_exe,
        str(EXTRACTION_SCRIPT),
        "--template",
        str(template),
        "--resources-dir",
        str(resources_dir),
        "--output-csv",
        str(output_csv),
        "--output-xlsx",
        str(output_xlsx),
        "--project-type",
        project_type,
        "--pico-json",
        pico_json_str,
        "--pipeline-mode",
        pipeline_mode,
    ]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate data extraction on the local PICO6 dataset using the stable CLI facade.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--datasets-dir",
        type=Path,
        default=DATASETS_DIR,
        help="Directory containing evaluation PDFs.",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=TEMPLATE_PATH,
        help="Excel template used for extraction.",
    )
    parser.add_argument(
        "--outputs-dir",
        type=Path,
        default=OUTPUTS_DIR,
        help="Directory for timestamped CSV/XLSX outputs.",
    )
    parser.add_argument(
        "--project-type",
        type=str,
        default="PICOS",
        choices=["PICOS", "PICO", "PECO", "PIRO"],
        help="Project type to pass through to the extraction CLI.",
    )
    parser.add_argument(
        "--pico-json",
        type=str,
        default="",
        help="Optional frontend-style PICO JSON string. If omitted, the eval PICO6.json is used.",
    )
    parser.add_argument(
        "--pipeline-mode",
        type=str,
        default="phase2",
        choices=["legacy", "phase1", "phase2"],
        help="Pipeline mode for evaluation. Defaults to phase2 so eval runs the newest multi-stage logic.",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    if not args.datasets_dir.exists():
        print(f"Error: datasets directory not found: {args.datasets_dir}")
        sys.exit(1)
    if not args.template.exists():
        print(f"Error: template file not found: {args.template}")
        sys.exit(1)
    if not EXTRACTION_SCRIPT.exists():
        print(f"Error: extraction script not found: {EXTRACTION_SCRIPT}")
        sys.exit(1)

    pdf_files = list(args.datasets_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"Error: no PDF files found in: {args.datasets_dir}")
        sys.exit(1)

    if args.pico_json:
        pico_json_str = args.pico_json
    else:
        if not PICO_JSON_PATH.exists():
            print(f"Error: eval PICO config not found: {PICO_JSON_PATH}")
            sys.exit(1)
        pico_json_str = json.dumps(load_pico_from_json(PICO_JSON_PATH), ensure_ascii=False)

    args.outputs_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_csv = args.outputs_dir / f"eval_{args.pipeline_mode}_{timestamp}.csv"
    output_xlsx = args.outputs_dir / f"eval_{args.pipeline_mode}_{timestamp}.xlsx"

    cmd = build_command(
        python_exe=sys.executable,
        resources_dir=args.datasets_dir,
        template=args.template,
        output_csv=output_csv,
        output_xlsx=output_xlsx,
        project_type=args.project_type,
        pico_json_str=pico_json_str,
        pipeline_mode=args.pipeline_mode,
    )

    print("=" * 60)
    print("Data Extraction Evaluation")
    print("=" * 60)
    print(f"PDF count:        {len(pdf_files)}")
    print(f"Project type:     {args.project_type}")
    print(f"Pipeline mode:    {args.pipeline_mode}")
    print(f"PICO payload:     {pico_json_str}")
    print(f"Template:         {args.template}")
    print(f"Output CSV:       {output_csv}")
    print(f"Output Excel:     {output_xlsx}")
    print(f"Reference XLSX:   {REFERENCE_XLSX}")
    print("=" * 60)
    print()

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    print(f"Starting extraction for {len(pdf_files)} papers...")
    print(f"Command: {' '.join(cmd)}")
    print()

    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        encoding="utf-8",
    )

    if process.stdout:
        print(process.stdout)

    if process.returncode != 0:
        error_msg = process.stderr.strip() or process.stdout.strip()
        print("\nExtraction failed.")
        print(f"Return code: {process.returncode}")
        print(f"Error:\n{error_msg}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("Extraction complete")
    print("=" * 60)
    print(f"Result file:      {output_xlsx}")
    print(f"Reference file:   {REFERENCE_XLSX}")
    print("=" * 60)


if __name__ == "__main__":
    main()
