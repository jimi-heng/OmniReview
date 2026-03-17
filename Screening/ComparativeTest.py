import AbstractScreening
import ThreeAgnets
import pandas as pd
import os
import time
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
import asyncio

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

    # 使用 merged_output.xlsx
    path = [REPO_ROOT / "data" / "merged_output.xlsx"]

    # 设置要读取的数据量
    NUM_SAMPLES = 100

    keywords = [
        """
        PICO: 
        Population (P): 转移性结直肠癌 (Metastatic colorectal cancer, mCRC)备注：不限定国家和人种
        Intervention (I): 4种药物：
                Cetuximab-β（泰州迈博太科药业）;
                Cetuximab（默克）;
                N01/A140（科伦药业）;
                Panitumumab（包括齐鲁制药帕妥尤单抗N01注射液
                等）

                单药或联合其他药物均可
        Comparison (C): 不限定对比干预
        Outcome (O): 有效性/安全性结局 备注：前期mapping阶段未做细化具体的有效性结局
        Study Design (S): RCT、CCT、Single arm trial、Cohort、Case series 排除 case report
        Extra requirements: 不限定检索年份
        """
    ]

    # === 主循环 ===
    for i in range(len(path)):
        print(f"\n正在处理文件: {os.path.basename(path[i])}")

        # === 方法1：使用 nrows 参数（推荐，效率最高）===
        try:
            # 读取第二个工作表的前200行
            excel_file = pd.ExcelFile(path[i])
            second_sheet_name = excel_file.sheet_names[1]
            print(f"读取第二个工作表: {second_sheet_name}")

            df = pd.read_excel(
                path[i],
                sheet_name=second_sheet_name,
                usecols=["title", "abstract", "label"],
                nrows=NUM_SAMPLES,  # 只读取前200行
                engine='openpyxl'
            )
            print(f"成功读取前 {len(df)} 行数据")

        except Exception as e:
            print(f"使用 nrows 参数读取失败: {e}")

            # === 方法2：先读取全部，然后用 iloc 切片 ===
            try:
                df = pd.read_excel(
                    path[i],
                    sheet_name=second_sheet_name,
                    usecols=["title", "abstract", "label"],
                    engine='openpyxl'
                )

                # 只取前200行
                df = df.iloc[:NUM_SAMPLES].reset_index(drop=True)
                print(f"读取全部数据后取前 {len(df)} 行")

            except Exception as e:
                print(f"所有读取方法都失败: {e}")
                raise

        # 显示数据信息
        print(f"最终处理 {len(df)} 行数据")
        print(f"数据列: {df.columns.tolist()}")

        df = df.reset_index(drop=True)
        keyword = keywords[i]

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
                # 创建默认label
                df['label'] = '0'
                print("创建了默认的 'label' 列，全部设为 '0'")

        # 映射标签值
        if df['label'].dtype == 'object':  # 如果是字符串类型
            label_map = {"Excluded": "0", "Included": "1"}
            df["label"] = df["label"].map(label_map).fillna(df["label"])

        # === 调用多智能体处理 ===
        await ThreeAgnets.use_agent_all(df, keyword, model1_name, model2_name, model3_name,
                                        AbstractScreening.PICOSsystemPromptReason,
                                        AbstractScreening.PICOSsystemPromptNoReason,
                                        AbstractScreening.PICOSuserPromptReason,
                                        AbstractScreening.PICOSuserPromptNoReason)

        # === 累积评估指标 ===
        Tp += ((df["Flag3"] == "1") & (df["label"] == "1")).sum()
        Fp += ((df["Flag3"] == "1") & (df["label"] != "1")).sum()
        Tn += ((df["Flag3"] != "1") & (df["label"] != "1")).sum()
        Fn += ((df["Flag3"] != "1") & (df["label"] == "1")).sum()

        mismatch = df[df["Flag3"] != df["label"]]

        cols = ["ID", "Title", "Abstract_clean", "Flag3", "Reason"]
        # 只选择存在的列
        available_cols = [col for col in cols if col in df.columns]
        if available_cols:
            mismatch_selected = mismatch[available_cols]

            output_path = output_dir / "mismatch_rows.csv"
            mismatch_selected.to_csv(output_path, index=False, encoding="utf-8-sig")
            print(f"不匹配的数据已保存到: {output_path}")
            print(f"不匹配数量: {len(mismatch_selected)}")
        else:
            print("警告：没有找到可保存的列")

    # === 各类指标计算函数 ===
    def calc_metrics(TP, FP, TN, FN):
        total = TP + FP + TN + FN
        accuracy = (TP + TN) / total if total > 0 else 0
        sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0
        specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
        precision = TP / (TP + FP) if (TP + FP) > 0 else 0
        f1 = 2 * precision * sensitivity / (precision + sensitivity) if (precision + sensitivity) > 0 else 0

        print(f"\n=== Metrics ===")
        print(f"Accuracy: {accuracy:.4f}")
        print(f"Sensitivity (Recall): {sensitivity:.4f}")
        print(f"Specificity: {specificity:.4f}")
        print(f"Precision: {precision:.4f}")
        print(f"F1: {f1:.4f}")
        print(f"Total samples: {total}")

    print("\nmodel1_name = " + model1_name)
    print("model2_name = " + model2_name)
    print("model3_name = " + model3_name)

    # === 输出三类结果 ===
    print("\n=== Results ===")
    print("TP:", Tp, "FP:", Fp, "TN:", Tn, "FN:", Fn)

    calc_metrics(Tp, Fp, Tn, Fn)

    # === 总耗时 ===
    end_time = time.time()
    elapsed = end_time - start_time
    print(f"\n总耗时: {elapsed:.2f} 秒")
    print(f"平均每行耗时: {elapsed / NUM_SAMPLES:.2f} 秒" if NUM_SAMPLES > 0 else "")

    print("\n=======================================================================================")


if __name__ == "__main__":
    asyncio.run(main())