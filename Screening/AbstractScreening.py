from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
import json
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
load_dotenv(override=True)

Entrez.email = "erzhuzi2023@outlook.com"

os.environ["DEEPSEEK_API_KEY"]=os.getenv("DEEPSEEK_API_KEY")
os.environ["OPENAI_API_KEY"]=os.getenv("OPENAI_API_KEY")
key=os.getenv("DMX_API_KEY")

DATA=[]
KEYWORDS=""

def abstract_screening(save_dir, model1=None, model2=None, model3=None):
    global KEYWORDS

    choice = 0
    while True:
        print("Download files: 1, Upload files: 2, Start abstract screening: 3")
        choice = int(input("Please choose: "))
        if (choice == 1):
            download_to_csv()
        elif choice == 2:
            upload_to_csv()
        elif choice == 3:
            break
        else:
            print("invalid number")
            continue

    df = pd.DataFrame(DATA)
    filename = os.path.join(save_dir, f"CSVList.csv")
    use_agent_all(df, KEYWORDS, model1, model2, model3)
    df=df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"保存到: {filename}")

#Download RIS files from PubMed
def download_to_csv():
    global DATA, KEYWORDS

    query = input("enter key words: ").strip()
    KEYWORDS = query + " " + KEYWORDS
    max_number = input("enter number: ").strip()

    #Search
    handle = Entrez.esearch(db="pubmed", term=query, retmax=max_number)
    record = Entrez.read(handle)
    handle.close()
    
    pmids = record["IdList"]
    print(f"找到 {len(pmids)} 篇文献")
    
    if not pmids:
        return
    
    handle = Entrez.efetch(db="pubmed", id=pmids, rettype="medline", retmode="text")
    records = list(Medline.parse(handle))
    handle.close()

    num=len(DATA)
    #Transform
    for idx, record in enumerate(records, start=1):
        row = {
            'ID': str(num+idx),
            'Title': record.get('TI', ''),
            'Abstract': record.get('AB', ''),
            'Authors': '; '.join(record.get('AU', [])),
            'Journal': record.get('JT', ''),
            'Publication_Date': record.get('DP', ''),
            'DOI': record.get('LID', record.get('AID', '')),
            'Keywords': '; '.join(record.get('OT', record.get('MH', []))),
            'Flag1': '',
            'Flag2': '',
            'Flag3': '',
            'Reason': ''
        }
        DATA.append(row)

def upload_to_csv():
    global DATA, KEYWORDS
    file_dir = input("enter RIS file: ").strip()
    

#Combine all the agents
def use_agent_all(csv_list, query, model1, model2, model3):
    use_agent1(csv_list, query, model1)
    use_agent2(csv_list, query, model2)

    for _, row in csv_list.iterrows():
        if (str(row["Flag1"]).strip().upper()) == (str(row["Flag2"]).strip().upper()):
            generate_reason(csv_list, row.to_dict(), query, model1)
        else:
            use_agent3(csv_list, row.to_dict(), query, model3)
            
#Judge by agent1
def use_agent1(csv_list, query, model):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Flag: 如果适合该主题，则为 "TRUE"，否则为 "FALSE"

        例如：
        [
        {{ "ID": "1", "Flag": "TRUE" }},
        ]

        【文献信息】
        {csv_list}

        请直接输出 JSON 数组，不要添加任何多余说明或文字。
    """

    agent = create_agent(
        model = model,
    )
    response = agent.invoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=csv_list)
        }]
    })
    data=json.loads(response["messages"][-1].content)
    #print(data)
    CollectAIResponse(csv_list, data, 1)

#Judge by agent2
def use_agent2(csv_list, query, model):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Flag: 如果适合该主题，则为 "TRUE"，否则为 "FALSE"

        例如：
        [
        {{ "ID": "1", "Flag": "TRUE" }},
        ]

        【文献信息】
        {csv_list}

        请直接输出 JSON 数组，不要添加任何多余说明或文字。
    """

    raw = model.invoke([
        {"role": "user", "content": prompt_template.format(query=query, csv_list=csv_list)}
    ])
    content = raw.content
    data = json.loads(content)
    #print(data)
    CollectAIResponse(csv_list, data, 2)

#Judge by agent3
def use_agent3(csv_list, row, query, model):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Flag: 如果适合该主题，则为 "TRUE"，否则为 "FALSE"
        - Reason: 给出50字左右的理由

        例如：
        [
        {{ "ID": "1", "Flag": "TRUE" , "Reason": "..."}},
        ]

        【文献信息】
        {csv_list}

        请直接输出 JSON 数组，不要添加任何多余说明或文字。
    """

    agent = create_agent(
        model = model,
    )
    response = agent.invoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=row)
        }]
    })
    data=json.loads(response["messages"][-1].content)
    #print(data)
    CollectAIResponse(csv_list, data, 3)

#Generate reason 
def generate_reason(csv_list, row, query, model):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Reason: 给出50字左右的理由

        例如：
        [
        {{ "ID": "1", "Reason": "..." }},
        ]

        【文献信息】
        {csv_list}

        请直接输出 JSON 数组，不要添加任何多余说明或文字。
    """
    agent = create_agent(
        model = model,
    )

    content = prompt_template.format(query=query, csv_list=row)
    response = agent.invoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=content)
        }]
    })
    #print(response["messages"][-1].content)
    data=json.loads(response["messages"][-1].content)
    #print(data)
    CollectReason(csv_list, data)

#Transform the AIResponse
def CollectAIResponse(csv_list, response, num):
    for e in response:
        id = e["ID"]
        flag = e["Flag"]
        csv_list.loc[csv_list["ID"] == id, f"Flag{num}"] = flag
        if (num == 3):
            reason = e["Reason"]
            csv_list.loc[csv_list["ID"] == id, "Reason"] = reason

#Add reason
def CollectReason(csv_list, response):
    for e in response:
        id = e["ID"]
        reason = e["Reason"]
        csv_list.loc[csv_list["ID"] == id, "Reason"] = reason

if __name__ == "__main__":
    save_dir = input("enter address: ").strip()

    model1 = init_chat_model(
        model="deepseek-chat", 
        model_provider="deepseek"
    )
    model2 = init_chat_model(
        model="gpt-5-minimal",
        base_url = "https://code.ppchat.vip/v1",
    )
    model3=ChatOpenAI(
        model="qwen-plus",
        base_url="https://www.dmxapi.cn/v1",
        api_key=key
    )

    abstract_screening(
        save_dir,
        model1,
        model2,
        model3
    )
