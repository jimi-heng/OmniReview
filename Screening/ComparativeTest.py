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
    model1_name = "claude-haiku-4-5-20251001"
    model2_name = "claude-haiku-4-5-20251001"
    model3_name = "gpt-4.1"

    model1 = ChatOpenAI(
        model=model1_name,
        base_url="https://www.dmxapi.cn/v1",
        api_key=key1,
        temperature=0
    )
    model2 = ChatOpenAI(
        model=model2_name,
        base_url="https://www.dmxapi.cn/v1",
        api_key=key2,
        temperature=0
    )
    model3 = ChatOpenAI(
        model=model3_name,
        base_url="https://www.dmxapi.cn/v1",
        api_key=key1,
        temperature=0
    )

    # === 指标统计初始化 ===
    Tp = Fp = Tn = Fn = 0

    start_time = time.time()

    output_dir = REPO_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)

    # path = [
    #     REPO_ROOT / "data" / "pico_001.csv",
    #     REPO_ROOT / "data" / "pico_002.csv",
    #     REPO_ROOT / "data" / "pico_003.csv",
    #     REPO_ROOT / "data" / "pico_004.csv",
    # ]
    # keywords = [
    #     """
    #     PICO: 
    #     Population (P): Aged 80 and over 80+ years, Adult 19-44 years, Diseases and disorders, Middle Aged 45-64 years, Young Adult 19-24 years, Aged 65-79 years, Healthy, Adolescent 13-18 years 
    #     Intervention (I): Beta Carotene Level, Selenium, Vitamin IV Solution Additives 
    #     Comparison (C): Placebo 
    #     Outcome (O): All Cause Mortality
    #     """,

    #     """
    #     PICO: 
    #     Population (P): Aged 80 and over 80+ years, Adult 19-44 years, Middle Aged 45-64 years, Surgery, Young Adult 19-24 years, General Anesthesia, Aged 65-79 years 
    #     Intervention (I): Surgical Department, Antiemetics And Antinauseants 
    #     Comparison (C): None 
    #     Outcome (O): Headache, Prolonged QT Interval, Cardiac Arrhythmia, Extrapyramidal Sign, Vomiting, Sedation, Constipation, Adverse Event, Wound Infection
    #     """,

    #     """
    #     PICO: 
    #     Population (P): Aged 80 and over 80+ years, Adult 19-44 years, Middle Aged 45-64 years, Type 2 Diabetes Mellitus, Young Adult 19-24 years, Type 1 Diabetes Mellitus, Aged 65-79 years 
    #     Intervention (I): Clinical education, Audits and feedback, Reminders, Case Management, Continuous quality improvement, Financial incentive, Patient Education, Electronic health records 
    #     Comparison (C): None 
    #     Outcome (O): Aspirin, Retinopathy, Hypoglycemia, Low Density Lipoprotein Cholesterol Measurement, Diabetic Foot Examination, Smoking cessation, Hyperglycemia, HbA1c level, Blood Pressure, Complication, Renal Care, Statins, Antihypertensive agents
    #     """,

    #     """
    #     PICO: 
    #     Population (P):Vascular Dementia, Not reported 
    #     Intervention (I): Galantamine, Rivastigmine, Donepezil 
    #     Comparison (C): Galantamine, Rivastigmine, Donepezil, Placebo 
    #     Outcome (O): Cognitive function, Clinical Finding, Alzheimer'a Disease Assessment Scale, Clinical Global Impression, Adverse Event, Activities Of Daily Living Assessment
    #     """
    # ]

    path = [REPO_ROOT / "data" / "merged_output.csv"]
    keywords = [
        """
        PICO: 
        Population (P): 铁缺乏但尚未贫血的儿童(0-6岁), 合并疾病?
        Intervention (I): 铁剂治疗(每日2 mg/kg元素铁的口服铁剂治疗,疗程为12周),剂量,疗程
        Comparison (C): 不进行铁剂治疗
        Outcome (O): Critical:血色素水平, 贫血的发生率, 生长发育指标; 
                    Important: 安全性指标：胃肠道反应、食欲下降, 神经认知发育, 肠道菌群, 感染性疾病患病率
        Extra requirements: Study design: SR、RCT、观察性研究
        """
    ]

    # === 主循环 ===
    for i in range(len(path)):
        print(f"\n正在处理文件: {os.path.basename(path[i])}")

        # 读取数据
        df = pd.read_csv(path[i], usecols=["Title", "Abstract_clean", "label"])[200:300]
        df = df.reset_index(drop=True)
        keyword = keywords[i]

        # 初始化中间列
        df["ID"] = range(len(df))
        df["Flag1"] = ""
        df["Flag2"] = ""
        df["Flag3"] = ""
        df["Reason"] = ""

        label_map = {0.0: "0", 1.0: "1"}
        df["label"] = df["label"].map(label_map)

        # === 调用多智能体处理 ===
        await ThreeAgnets.use_agent_all(df, keyword, model1_name, model2_name, model3_name,
                                             AbstractScreening.systemPromptReason,
                                             AbstractScreening.systemPromptNoReason,
                                             AbstractScreening.userPromptReason,
                                             AbstractScreening.userPromptNoReason)

        # === 累积评估指标 ===
        Tp += ((df["Flag3"] == "1") & (df["label"] == "1")).sum()
        Fp += ((df["Flag3"] == "1") & (df["label"] != "1")).sum()
        Tn += ((df["Flag3"] != "1") & (df["label"] != "1")).sum()
        Fn += ((df["Flag3"] != "1") & (df["label"] == "1")).sum()

        mismatch = df[df["Flag3"] != df["label"]]

        cols = ["ID", "Title", "Abstract_clean", "Flag3", "Reason"]
        mismatch_selected = mismatch[cols]

        output_path = output_dir / "mismatch_rows.csv"
        mismatch_selected.to_csv(output_path, index=False, encoding="utf-8-sig")

    # === 各类指标计算函数 ===
    def calc_metrics(TP, FP, TN, FN):
        accuracy = (TP + TN) / (TP + FP + TN + FN) if (TP + FP + TN + FN) > 0 else 0
        sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0
        specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
        precision = TP / (TP + FP) if (TP + FP) > 0 else 0
        f1 = 2 * precision * sensitivity / (precision + sensitivity) if (precision + sensitivity) > 0 else 0

        print(f"\n=== Metrics ===")
        print(f"Accuracy: {accuracy:.2f}")
        print(f"Sensitivity (Recall): {sensitivity:.2f}")
        print(f"Specificity: {specificity:.2f}")
        print(f"Precision: {precision:.2f}")
        print(f"F1: {f1:.2f}")

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

    print("\n=======================================================================================")


if __name__ == "__main__":
    asyncio.run(main())
