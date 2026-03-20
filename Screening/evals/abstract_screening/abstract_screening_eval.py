import sys
from pathlib import Path

# ✅ 必须在 import 前
ROOT = Path(__file__).resolve().parents[3]
sys.path.append(str(ROOT))

from Screening import AbstractScreening
from Screening import ThreeAgents

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
    # === 模型设定 ===
    model1_name = "gpt-4.1"
    model2_name = "gpt-4.1-mini"
    model3_name = "gpt-4.1"

    # === 指标统计初始化 ===
    Tp = Fp = Tn = Fn = 0

    start_time = time.time()

    output_dir = REPO_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # === datasets路径 ===
    DATA_DIR = SCRIPT_DIR / "datasets"

    file_path = DATA_DIR / "SRSSH2025102108-firstlevel screening-final.xlsx"
    pico_path = DATA_DIR / "PICO_SRSSH.json"

    # === 读取 PICO JSON ===
    with open(pico_path, "r", encoding="utf-8") as f:
        pico_json = json.load(f)

    query = json.dumps(pico_json, ensure_ascii=False, indent=2)

    # 设置要读取的数据量
    NUM_SAMPLES = 100

    print(f"\n正在处理文件: {os.path.basename(file_path)}")

    second_sheet_name = None  # ✅ 防止未定义

    try:
        excel_file = pd.ExcelFile(file_path)
        second_sheet_name = excel_file.sheet_names[1]
        print(f"读取第二个工作表: {second_sheet_name}")

        df = pd.read_excel(
            file_path,
            sheet_name=second_sheet_name,
            usecols=["title", "abstract", "label"],
            nrows=NUM_SAMPLES,
            engine='openpyxl'
        )
        print(f"成功读取前 {len(df)} 行数据")

    except Exception as e:
        print(f"使用 nrows 参数读取失败: {e}")

        if second_sheet_name is None:
            raise RuntimeError("Excel读取失败，无法获取sheet名称")

        df = pd.read_excel(
            file_path,
            sheet_name=second_sheet_name,
            usecols=["title", "abstract", "label"],
            engine='openpyxl'
        )

        df = df.iloc[:NUM_SAMPLES].reset_index(drop=True)
        print(f"读取全部数据后取前 {len(df)} 行")

    print(f"最终处理 {len(df)} 行数据")
    print(f"数据列: {df.columns.tolist()}")

    df = df.reset_index(drop=True)

    # 初始化中间列
    df["ID"] = range(len(df))
    df["Flag1"] = ""
    df["Flag2"] = ""
    df["Flag3"] = ""
    df["Reason"] = ""

    # 处理标签列
    if 'label' not in df.columns:
        if 'abstract_screening_decision' in df.columns:
            df = df.rename(columns={'abstract_screening_decision': 'label'})
            print("已将 'abstract_screening_decision' 重命名为 'label'")
        else:
            print("警告：未找到 'label' 或 'abstract_screening_decision' 列")
            df['label'] = '0'

    # 映射标签
    if df['label'].dtype == 'object':
        label_map = {"Excluded": "0", "Included": "1"}
        df["label"] = df["label"].map(label_map).fillna(df["label"])

    # === 调用多智能体 ===
    await ThreeAgents.use_agent_all(
        df, query,
        model1_name, model2_name, model3_name,
        AbstractScreening.PICOSsystemPromptReason,
        AbstractScreening.PICOSsystemPromptNoReason,
        AbstractScreening.PICOSuserPromptReason,
        AbstractScreening.PICOSuserPromptNoReason
    )

    # === 指标计算 ===
    Tp += ((df["Flag3"] == "1") & (df["label"] == "1")).sum()
    Fp += ((df["Flag3"] == "1") & (df["label"] != "1")).sum()
    Tn += ((df["Flag3"] != "1") & (df["label"] != "1")).sum()
    Fn += ((df["Flag3"] != "1") & (df["label"] == "1")).sum()

    mismatch = df[df["Flag3"] != df["label"]]

    cols = ["ID", "Title", "Abstract_clean", "Flag3", "Reason"]
    available_cols = [col for col in cols if col in df.columns]

    if available_cols:
        mismatch_selected = mismatch[available_cols]
        output_path = output_dir / "mismatch_rows.csv"
        mismatch_selected.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"不匹配的数据已保存到: {output_path}")
        print(f"不匹配数量: {len(mismatch_selected)}")

    # === 指标函数 ===
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
    print(f"\n总耗时: {elapsed:.2f} 秒")
    print(f"平均每行耗时: {elapsed / NUM_SAMPLES:.2f} 秒" if NUM_SAMPLES > 0 else "")


if __name__ == "__main__":
    asyncio.run(main())