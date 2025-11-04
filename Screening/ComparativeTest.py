import AbstractScreening
import pandas as pd
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
load_dotenv(override=True)

key=os.getenv("DMX_API_KEY")

model1_name="claude-haiku-4-5-20251001"
model2_name="gemini-2.5-flash"
model3_name="gpt-5-mini"

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

path = r"C:\Users\erzhu\Desktop\GRP_dataset\20240827_Systematic_Review_Data\20240827_val_set.csv"

keywords="NSAIDs PD adverse effects"

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

df = pd.read_csv(path, usecols=["Abstract_clean", "label"])
df["ID"]=range(len(df))
df["Flag1"]=""
df["Flag2"]=""
df["Flag3"]=""
df["Reason"]=""

AbstractScreening.use_agent_all(df[:20], keywords, model1, model2, model3)

for i in range(20):
    #In
    if (df.loc[i, "Flag3"]==1.0):
        if (df.loc[i, "label"]==1.0):
            TP_In+=1
        else:
            FP_In+=1
    else:
        if (df.loc[i, "label"]==1.0):
            FN_In+=1
        else:
            TN_In+=1

    #Ex
    if (df.loc[i, "Flag3"]==0.0):
        if (df.loc[i, "label"]==0.0):
            TP_Ex+=1
        else:
            FP_Ex+=1
    else:
        if (df.loc[i, "label"]==0.0):
            FN_Ex+=1
        else:
            TN_Ex+=1

    #May
    if (df.loc[i, "Flag3"]==0.5):
        if (df.loc[i, "label"]==0.5):
            TP_May+=1
        else:
            FP_May+=1
    else:
        if (df.loc[i, "label"]==0.5):
            FN_May+=1
        else:
            TN_May+=1

print(df[:20])

print("\n=== Include ===")
print("TP:", TP_In, "FP:", FP_In, "TN:", TN_In, "FN:", FN_In)

print("\n=== Exclude ===")
print("TP:", TP_Ex, "FP:", FP_Ex, "TN:", TN_Ex, "FN:", FN_Ex)

print("\n=== Maybe ===")
print("TP:", TP_May, "FP:", FP_May, "TN:", TN_May, "FN:", FN_May)