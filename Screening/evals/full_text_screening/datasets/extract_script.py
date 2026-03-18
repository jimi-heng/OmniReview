import json
import pandas as pd

input_file = "PICO15.json"
output_file = "PICO15_FullTextAssessment.csv"

# 读取 JSON
with open(input_file, "r", encoding="utf-8") as f:
    data = json.load(f)

# 提取需要的字段
rows = []
for item in data:
    rows.append({
        "Paper_Index": item.get("Paper_Index"),
        "Full-text_Assessment": item.get("Full-text_Assessment")
    })

# 保存为 CSV
df = pd.DataFrame(rows)
df.to_csv(output_file, index=False, encoding="utf-8-sig")

print(f"CSV 已生成: {output_file}")