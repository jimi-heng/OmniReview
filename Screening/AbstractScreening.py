from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
import re
import json5
import asyncio
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
load_dotenv(override=True)

Entrez.email = "erzhuzi2023@outlook.com"

key1=os.getenv("DMX_API_KEY_1")
key2=os.getenv("DMX_API_KEY_2")

DATA=[]
KEYWORDS=""

async def abstract_screening(save_dir, model1=None, model2=None, model3=None):
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
    await use_agent_all(df, KEYWORDS, model1, model2, model3)
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
    for idx, record in enumerate(records, start=0):
        row = {
            'ID': num+idx,
            'Title': record.get('TI', ''),
            'Abstract': record.get('AB', ''),
            'Authors': '; '.join(record.get('AU', [])),
            'Journal': record.get('JT', ''),
            'Publication_Date': record.get('DP', ''),
            'DOI': extract_doi(record),
            'Keywords': '; '.join(record.get('OT', record.get('MH', []))),
            'Flag1': '',
            'Flag2': '',
            'Flag3': '',
            'Reason': ''
        }
        DATA.append(row)

#Upload files
def upload_to_csv():
    global DATA, KEYWORDS
    file_dir = input("enter RIS file: ").strip()

#Get DOI 
def extract_doi(record):
    doi_pattern = re.compile(r"10\.\d{4,9}/[^\s\]]+", re.IGNORECASE)
    for key in ("LID", "AID"):
        val = record.get(key)
        if not val:
            continue
        if isinstance(val, list):
            text = " ".join(val)
        else:
            text = str(val)
        match = doi_pattern.search(text)
        if match:
            return match.group(0)
    return ""

#Combine all the agents
async def use_agent_all(csv_list, query, model1, model2, model3):
    await asyncio.gather(
        use_agent_first1(csv_list, query, model1, 1),
        use_agent_first2(csv_list, query, model2, 2)
    )
       
    #Check whether Flag1 is eaqual to Flag2
    same_mask = csv_list["Flag1"].astype(str).str.strip().str.upper() == csv_list["Flag2"].astype(str).str.strip().str.upper()

    #If equal, copy the values in Flag1 to Flag3
    csv_list.loc[same_mask, "Flag3"] = csv_list.loc[same_mask, "Flag1"]
    
    #Get the different values
    ListAgent3 = csv_list.loc[~same_mask].to_dict("records")

    if ListAgent3:
        print(len(ListAgent3))
        await use_agent_after(csv_list, ListAgent3, query, model3) 

#Judge by agent1
async def use_agent_first1(csv_list, query, model, num):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。
        已有两位科研助手对这些文献是否合适的判断不一致, 请更严谨的判断

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回, 不要输出多余的符号。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Flag: 如果适合该主题，则为 1.0,否则为 0.0, 不确定为 0.5
        - 不要使用 Markdown 格式（例如不要输出 ```json, 也不要输出```)
        - Reason: 给出50字左右的理由

        例如：
        [
        {{ "ID": 1, "Flag": 1,0 , "Reason": "..."}},
        ]

        【文献信息】
        {csv_list}

        请严格输出 JSON 数组，不要添加任何多余说明或文字。
    """

    agent = create_agent(
        model = model,
    )
    response = await agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=csv_list)
        }]
    })
    #print(response)
    response=response["messages"][-1].content
    response=re.sub(r'"\s+"(\d+)"', r'"\1"', response)
    data=json5.loads(response)
    print("First agent done")
    CollectAIResponse(csv_list, data, num)

#Judge by agent2
async def use_agent_first2(csv_list, query, model, num):
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
        - 不要使用 Markdown 格式（例如不要输出 ```json, 也不要输出```)
        - Flag: 如果适合该主题，则为 1.0, 否则为 0.0, 不确定为 0.5

        例如：
        [
        {{ "ID": 1, "Flag": 1.0 }},
        ]

        【文献信息】
        {csv_list}

        请严格输出 JSON 数组，不要添加任何多余说明或文字。
    """

    agent = create_agent(
        model = model,
    )
    response = await agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=csv_list)
        }]
    })
    #print(response)
    response=response["messages"][-1].content
    response=re.sub(r'"\s+"(\d+)"', r'"\1"', response)
    data=json5.loads(response)
    print("Second agent done")
    CollectAIResponse(csv_list, data, num)

#Judge by agent3
async def use_agent_after(csv_list, ListAgent3, query, model):
    prompt_template = """
        你是一名科研助手，请评估以下文献是否适合用于撰写主题为“{query}”的学术论文。
        已有两位科研助手对这些文献是否合适的判断不一致, 请更严谨的判断

        【任务要求】
        1. 阅读下方提供的文献信息列表。
        2. 对每篇文献判断是否与主题密切相关。
        3. 仅根据文献标题和摘要内容进行判断。
        4. 输出结果时，必须严格按照指定 JSON 格式返回, 不要输出多余的符号。

        【输出格式要求】
        返回一个 JSON 数组（不是字符串、不是自然语言解释），每个元素包括以下字段：
        - 读取每篇文献中的ID
        - Flag: 如果适合该主题，则为 1.0,否则为 0.0, 不确定为 0.5。已有两位科研助手对这些文献是否合适的判断不一致, 请更严谨的判断
        - 不要使用 Markdown 格式（例如不要输出 ```json, 也不要输出```)
        - Reason: 给出50字左右的理由

        例如：
        [
        {{ "ID": 1, "Flag": 1,0 , "Reason": "..."}},
        ]

        【文献信息】
        {csv_list}

        请严格输出 JSON 数组，不要添加任何多余说明或文字。
    """

    agent = create_agent(
        model = model,
    )
    response = await agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": prompt_template.format(query=query, csv_list=ListAgent3)
        }]
    })
    response=response["messages"][-1].content
    response=re.sub(r'"\s+"(\d+)"', r'"\1"', response)
    data=json5.loads(response)
    print("Last agent done")
    CollectAIResponse(csv_list, data, 3)

#Transform the AIResponse
def CollectAIResponse(csv_list, response, num):
    for e in response:
        id = e["ID"]
        flag = e["Flag"]
        csv_list.loc[csv_list["ID"] == id, f"Flag{num}"] = flag
        if (num == 3 or num == 1):
            reason = e["Reason"]
            csv_list.loc[csv_list["ID"] == id, "Reason"] = reason

async def main():
    #save_dir = input("enter address: ").strip()
    save_dir = r"C:\Users\erzhu\Desktop\GRP-MultiAgent\Screening"

    model1_name="gpt-4.1-nano"
    model2_name="gpt-4.1-nano"
    model3_name="gpt-4.1"

    model1 = ChatOpenAI(
        model=model1_name, 
        base_url="https://www.dmxapi.cn/v1",
        api_key=key1
    )
    model2 = ChatOpenAI(
        model=model2_name,
        base_url="https://www.dmxapi.cn/v1",
        api_key=key2
    )
    model3 = ChatOpenAI(
        model=model3_name,
        base_url="https://www.dmxapi.cn/v1",
        api_key=key1
    )

    await abstract_screening(
        save_dir,
        model1,
        model2,
        model3
    )

if __name__ == "__main__":
    asyncio.run(main())