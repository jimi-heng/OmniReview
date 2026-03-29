import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT))

from Screening import AbstractScreening
from Screening.abstract_screening import ThreeAgents

import pandas as pd
import os
import time
from dotenv import load_dotenv
import asyncio
import json

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

load_dotenv(SCRIPT_DIR / ".env", override=True)

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")


async def main():
    model1_name = "gpt-4.1"
    model2_name = "gpt-4.1-mini"
    model3_name = "gpt-4.1"

    Tp = Fp = Tn = Fn = 0

    start_time = time.time()

    output_dir = REPO_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Dataset path
    DATA_DIR = SCRIPT_DIR / "datasets"

    file_path = DATA_DIR / "merged_output.csv"
    pico_path = DATA_DIR / "PICO.json"

    # Load PICO JSON
    with open(pico_path, "r", encoding="utf-8") as f:
        pico_json = json.load(f)

    query = json.dumps(pico_json, ensure_ascii=False, indent=2)

    NUM_SAMPLES = 200

    print(f"\nProcessing file: {os.path.basename(file_path)}")

    # Read data (CSV / XLSX compatible)
    if file_path.suffix == ".csv":
        print("Detected CSV file")

        df = pd.read_csv(
            file_path,
            encoding="utf-8-sig",
            header=None
        )

        # Select row range
        df = df.iloc[50:250]

        # Specify columns by index
        TITLE_COL = 1
        ABSTRACT_COL = 14
        LABEL_COL = df.columns[-1]

        df = df.rename(columns={
            TITLE_COL: "title",
            ABSTRACT_COL: "abstract",
            LABEL_COL: "label"
        })

        df = df[["title", "abstract", "label"]]

    else:
        print("Detected Excel file")

        excel_file = pd.ExcelFile(file_path)
        sheet_names = excel_file.sheet_names

        if len(sheet_names) < 2:
            raise RuntimeError("Excel must contain at least two sheets")

        second_sheet_name = sheet_names[1]
        print(f"Reading second sheet: {second_sheet_name}")

        df = pd.read_excel(
            file_path,
            sheet_name=second_sheet_name,
            skiprows=50,
            nrows=NUM_SAMPLES,
            engine="openpyxl"
        )

    print(f"Successfully loaded {len(df)} rows")

    # Normalize column names
    df.columns = df.columns.str.strip().str.lower()

    # Automatically match column names
    col_map = {
        "title": None,
        "abstract": None,
        "label": None
    }

    for col in df.columns:
        if "title" in col:
            col_map["title"] = col
        elif "abstract" in col:
            col_map["abstract"] = col
        elif "label" in col or "decision" in col:
            col_map["label"] = col

    if None in col_map.values():
        raise RuntimeError(f"Column mismatch, current columns: {df.columns.tolist()}")

    df = df.rename(columns={
        col_map["title"]: "title",
        col_map["abstract"]: "abstract",
        col_map["label"]: "label"
    })

    df = df[["title", "abstract", "label"]]

    print(f"Columns: {df.columns.tolist()}")

    df = df.reset_index(drop=True)

    # Initialize columns
    df["ID"] = range(len(df))
    df["Flag1"] = ""
    df["Flag2"] = ""
    df["Flag3"] = ""
    df["Reason"] = ""

    # Normalize label values
    # CSV: 1 = Included, 0 = Excluded
    df["label"] = df["label"].astype(str).str.strip()

    label_map = {
        "1": "1", "0": "0",
        "Included": "1", "Excluded": "0",
        "included": "1", "excluded": "0"
    }

    df["label"] = df["label"].map(label_map).fillna(df["label"])

    # Call multi-agent system
    await ThreeAgents.use_agent_all(
        df, query,
        model1_name, model2_name, model3_name,
        AbstractScreening.PICOSsystemPromptReason,
        AbstractScreening.PICOSsystemPromptNoReason,
        AbstractScreening.PICOSuserPromptReason,
        AbstractScreening.PICOSuserPromptNoReason
    )

    # Metrics calculation
    Tp += ((df["Flag3"] == "1") & (df["label"] == "1")).sum()
    Fp += ((df["Flag3"] == "1") & (df["label"] != "1")).sum()
    Tn += ((df["Flag3"] != "1") & (df["label"] != "1")).sum()
    Fn += ((df["Flag3"] != "1") & (df["label"] == "1")).sum()

    mismatch = df[df["Flag3"] != df["label"]]

    cols = ["ID", "title", "abstract", "Flag3", "Reason"]
    available_cols = [col for col in cols if col in df.columns]

    if available_cols:
        mismatch_selected = mismatch[available_cols]
        output_path = output_dir / "mismatch_rows.csv"
        mismatch_selected.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"Mismatched data saved to: {output_path}")
        print(f"Mismatch count: {len(mismatch_selected)}")

    # Metric function
    def calc_metrics(TP, FP, TN, FN):
        total = TP + FP + TN + FN
        accuracy = (TP + TN) / total if total > 0 else 0
        sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0
        specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
        precision = TP / (TP + FP) if (TP + FP) > 0 else 0
        f1 = 2 * precision * sensitivity / (precision + sensitivity) if (precision + sensitivity) > 0 else 0

        print(f"\n=== Metrics ===")
        print(f"Accuracy: {accuracy:.4f}")
        print(f"Sensitivity: {sensitivity:.4f}")
        print(f"Specificity: {specificity:.4f}")
        print(f"Precision: {precision:.4f}")
        print(f"F1: {f1:.4f}")
        print(f"Total samples: {total}")

    print("\n=== Results ===")
    print("TP:", Tp, "FP:", Fp, "TN:", Tn, "FN:", Fn)

    calc_metrics(Tp, Fp, Tn, Fn)

    end_time = time.time()
    elapsed = end_time - start_time
    print(f"\nTotal time: {elapsed:.2f} seconds")
    print(f"Average time per row: {elapsed / NUM_SAMPLES:.2f} seconds" if NUM_SAMPLES > 0 else "")


if __name__ == "__main__":
    asyncio.run(main())