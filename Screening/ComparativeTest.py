import AbstractScreening
import pandas as pd
import os
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from sklearn.metrics import precision_recall_fscore_support, accuracy_score

load_dotenv(override=True)

key=os.getenv("DMX_API_KEY")

model1_name="gpt-4.1-nano"
model2_name="gpt-4.1-mini"
model3_name="gpt-4.1"

model1 = ChatOpenAI(
    model=model1_name, 
    base_url="https://www.dmxapi.cn/v1",
    api_key=key
)
model2 = ChatOpenAI(
    model=model2_name,
    base_url="https://www.dmxapi.cn/v1",
    api_key=key
)
model3 = ChatOpenAI(
    model=model3_name,
    base_url="https://www.dmxapi.cn/v1",
    api_key=key
)

TP_In=0  #True Positive   Judge include, it actually include
FP_In=0  #False Positive  Judge include, but it do not include(exclude + maybe)
TN_In=0  #True Negative   Judge do not include, it actually do not include
FN_In=0  #False Negative  Judge do not include, but it include

TP_Ex=0
FP_Ex=0
TN_Ex=0
FN_Ex=0

TP_May=0
FP_May=0
TN_May=0
FN_May=0

start_time = time.time()

num=25
all_df = []

path = [
    r"C:\Users\erzhu\Desktop\GRP_dataset\20240827_Systematic_Review_Data\20240827_val_set.csv",
    r"C:\Users\erzhu\Desktop\GRP_dataset\20240827_Systematic_Review_Data\20240827_random_test_set.csv",
    r"C:\Users\erzhu\Desktop\GRP_dataset\20240827_Systematic_Review_Data\20240827_HIV_test_set.csv",
    r"C:\Users\erzhu\Desktop\GRP_dataset\20240827_Systematic_Review_Data\20240827_heart_test_set.csv"
]

for j in range(4):
    df = pd.read_csv(path[j], usecols=["Abstract_clean", "label"])[:num]
    df_meta = pd.read_csv(path[j], usecols=["Objective", "Selection_criteria"])
    keywords = df_meta.loc[0, "Objective"] + " " +df_meta.loc[0, "Selection_criteria"]

    df["ID"]=range(len(df))
    df["Flag1"]=""
    df["Flag2"]=""
    df["Flag3"]=""
    df["Reason"]=""

    AbstractScreening.use_agent_all(df, keywords, model1, model2, model3)

    label_map = {0.0: 0, 0.5: 2, 1.0: 1}
    df["label"] = df["label"].map(label_map)
    df["Flag3"] = df["Flag3"].map(label_map)

    TP_In += ((df["Flag3"] == 1) & (df["label"] == 1)).sum()
    FP_In += ((df["Flag3"] == 1) & (df["label"] != 1)).sum()
    TN_In += ((df["Flag3"] != 1) & (df["label"] != 1)).sum()
    FN_In += ((df["Flag3"] != 1) & (df["label"] == 1)).sum()

    TP_Ex += ((df["Flag3"] == 0) & (df["label"] == 0)).sum()
    FP_Ex += ((df["Flag3"] == 0) & (df["label"] != 0)).sum()
    TN_Ex += ((df["Flag3"] != 0) & (df["label"] != 0)).sum()
    FN_Ex += ((df["Flag3"] != 0) & (df["label"] == 0)).sum()

    TP_May += ((df["Flag3"] == 2) & (df["label"] == 2)).sum()
    FP_May += ((df["Flag3"] == 2) & (df["label"] != 2)).sum()
    TN_May += ((df["Flag3"] != 2) & (df["label"] != 2)).sum()
    FN_May += ((df["Flag3"] != 2) & (df["label"] == 2)).sum()

    all_df.append(df)

print("\n=== Include ===")
print("TP:", TP_In, "FP:", FP_In, "TN:", TN_In, "FN:", FN_In)

print("\n=== Exclude ===")
print("TP:", TP_Ex, "FP:", FP_Ex, "TN:", TN_Ex, "FN:", FN_Ex)

print("\n=== Maybe ===")
print("TP:", TP_May, "FP:", FP_May, "TN:", TN_May, "FN:", FN_May)

def calc_metrics(TP, FP, TN, FN, name):
    # 准确率（Accuracy）：预测正确的比例
    accuracy = (TP + TN) / (TP + FP + TN + FN) if (TP + FP + TN + FN) > 0 else 0
    
    # 灵敏度（Sensitivity / Recall）：在所有“实际为正”的样本中，正确预测为正的比例
    sensitivity = TP / (TP + FN) if (TP + FN) > 0 else 0   
    
    # 特异度（Specificity）：在所有“实际为负”的样本中，正确预测为负的比例
    specificity = TN / (TN + FP) if (TN + FP) > 0 else 0
    
    # 精确率（Precision）：在所有预测为正的样本中，真正为正的比例
    precision = TP / (TP + FP) if (TP + FP) > 0 else 0
    
    # F1分数（F1-score）：Precision 和 Recall 的调和平均，更全面衡量模型性能
    f1 = 2 * precision * sensitivity / (precision + sensitivity) if (precision + sensitivity) > 0 else 0

    print(f"\n=== {name} Metrics ===")
    print(f"Accuracy_{name}: {accuracy:.2f}    # 准确率（正确预测的总体比例）")
    print(f"Sensitivity_{name} (Recall): {sensitivity:.2f}    # 灵敏度 / 召回率")
    print(f"Specificity_{name}: {specificity:.2f}    # 特异度（正确识别负例的能力）")
    print(f"Precision_{name}: {precision:.2f}    # 精确率（预测为正中实际为正的比例）")
    print(f"F1_{name}: {f1:.2f}    # F1分数（Precision 与 Recall 的平衡指标）")

def calc_macro_weighted(df, label_col="label", pred_col="Flag3"):
    y_true = df[label_col]
    y_pred = df[pred_col]

    acc = accuracy_score(y_true, y_pred)
    precision_macro, recall_macro, f1_macro, _ = precision_recall_fscore_support(
        y_true, y_pred, average='macro', zero_division=0
    )
    precision_weighted, recall_weighted, f1_weighted, _ = precision_recall_fscore_support(
        y_true, y_pred, average='weighted', zero_division=0
    )

    print("\n=== Overall Performance ===")
    print(f"Accuracy_total: {acc:.2f}")
    print(f"Macro-average: Precision={precision_macro:.2f}, Recall={recall_macro:.2f}, F1={f1_macro:.2f}")
    print(f"Weighted-average: Precision={precision_weighted:.2f}, Recall={recall_weighted:.2f}, F1={f1_weighted:.2f}")

merged_df = pd.concat(all_df, ignore_index=True)

# === 输出三类结果 ===
calc_metrics(TP_In, FP_In, TN_In, FN_In, "Include")
calc_metrics(TP_Ex, FP_Ex, TN_Ex, FN_Ex, "Exclude")
calc_metrics(TP_May, FP_May, TN_May, FN_May, "Maybe")

calc_macro_weighted(merged_df, label_col="label", pred_col="Flag3")

end_time = time.time()
elapsed = end_time - start_time
print(f"\n总耗时: {elapsed:.2f} 秒")