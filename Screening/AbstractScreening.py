from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
import re
import asyncio
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
load_dotenv(override=True)

Entrez.email = "erzhuzi2023@outlook.com"

key1=os.getenv("DMX_API_KEY_1")
key2=os.getenv("DMX_API_KEY_2")

whole_paper_list=[]
topic_keywords=""

systemPromptReason = """
    Role: 
        You are an expert biomedical literature evaluator specializing in evidence-based medicine and systematic reviews.
    Goal:
        Given a PICO (Population, Intervention, Comparison, Outcome) description and a Topic, 
        your task is to determine whether a provided research paper is relevant (i.e., suitable for inclusion) 
        or not relevant based on how well the paper aligns with the PICO and Topic.
    Instructions:
        1. Carefullly read the Topic and PICO information.
        2. Review the paper's title and abstract.
        3. Decide if the paper's content meaningfully fits the PICO question and Topic.
        4. Evaluate relevance using the following rules:
            1. The paper must clearly match at least two PICO components (Population, Intervention, Comparison, or Outcome).
        5. Your response must include:
            1. ID: the id of this paper.
            2. Flag: return 1 if include, 0 if exclude.
            3. Reason: a brief explanation of which PICO componets are contained and why this essay was include or exclude. In Chinese
    PICO description:
        1. Population (P): The study targets the same or a similar group of patients/subjects.
        2. Intervention (I): The main intervention matches or closely relates to that in the PICO.
        3. Comparison (C): The study includes a relevant control or comparison group (if applicable).
        4. Outcome (O): The study measures or reports on the same or relevant outcomes.
"""

systemPromptNoReason = """
    Role: 
        You are an expert biomedical literature evaluator specializing in evidence-based medicine and systematic reviews.
    Goal:
        Given a PICO (Population, Intervention, Comparison, Outcome) description and a Topic, 
        your task is to determine whether a provided research paper is relevant (i.e., suitable for inclusion) 
        or not relevant based on how well the paper aligns with the PICO and Topic.
    Instructions:
        1. Carefullly read the Topic and PICO information.
        2. Review the paper's title and abstract.
        3. Decide if the paper's content meaningfully fits the PICO question and Topic.
        4. Evaluate relevance using the following rules:
            1. The paper must clearly match at least two PICO components (Population, Intervention, Comparison, or Outcome).
        5. Your response must include:
            1. ID: the id of this paper.
            2. Flag: return 1 if include, 0 if exclude. Ignore Reason
    PICO description:
        1. Population: The study targets the same or a similar group of patients/subjects.
        2. Intervention: The main intervention matches or closely relates to that in the PICO.
        3. Comparison: The study includes a relevant control or comparison group (if applicable).
        4. Outcome: The study measures or reports on the same or relevant outcomes.
"""

userPromptReason = """
    PICO_Topic dictionary: 
        {query}
    Papers: 
        {paper_list}
    Task:
        1. Evaluate each paper independently.
        2. A paper is suitable (Flag=1) if it matches at least two PICO components (Population, Intervention, Comparison, Outcome).
        3. If fewer than two components match, Flag=0.
        4. Provide a short reasoning for each paper explaining which PICO components were matched. In Chinese
"""

userPromptNoReason = """
    PICO_Topic dictionary: 
        {query}
    Papers: 
        {paper_list}
    Task:
        1. Evaluate each paper independently.
        2. A paper is suitable (Flag=1) if it matches at least two PICO components (Population, Intervention, Comparison, Outcome).
        3. If fewer than two components match, Flag=0.
        4. Ignore Reason
"""

#The type of single value in the list
class Judge_Base(BaseModel):
    """Judge whether the essay is suitable"""
    ID: int = Field(..., description = "The ID of the eaasy")
    Flag: Literal[1, 0] = Field(..., description = "the judge of whether the value is suitbale")
    Reason: Optional[str] = Field(None, description="the reason of the judge")

#The whole list
class Judge_List(BaseModel):
    """List of every essay's judge"""
    judge_list: List[Judge_Base_Reason] = Field(..., description="the list of each essay's judge")

async def abstract_screening(save_dir, model1=None, model2=None, model3=None):
    global topic_keywords

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

    # Population = input("Enter Population: ").strip()
    # Intervention = input("Enter Intervention: ").strip()
    # Comparision = input("Enter Comparision: ").strip()
    # Outcome = input("Enter Outcome: ").strip()

    # query = {
    #     "Topic" : topic_keywords,
    #     "Population" : Population,
    #     "Intervention" : Intervention,
    #     "Comparision" : Comparision,
    #     "Outcome" : Outcome
    # }

    pico1 = {
        "Topic": "Wound Healing Rate",
        "Population": "Adults with acute wounds or surgical incisions",
        "Intervention": "Application of medical-grade honey dressings (e.g., Manuka honey)",
        "Comparison": "Standard wound care (e.g., saline or silver dressings)",
        "Outcome": "Shorter wound healing time (faster recovery)"
  }

    paper_list = pd.DataFrame(whole_paper_list)
    filename = os.path.join(save_dir, f"CSVList.csv")
    await use_agent_all(paper_list, pico1, model1, model2, model3)
    paper_list=paper_list.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"保存到: {filename}")

#Download RIS files from PubMed
def download_to_csv():
    global whole_paper_list, topic_keywords

    query = input("enter key words: ").strip()
    topic_keywords = query + " " + topic_keywords
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

    num=len(whole_paper_list)
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
            'topic_keywords': '; '.join(record.get('OT', record.get('MH', []))),
            'Flag1': '',
            'Flag2': '',
            'Flag3': '',
            'Reason': ''
        }
        whole_paper_list.append(row)

#Upload files
def upload_to_csv():
    global whole_paper_list, topic_keywords
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
async def use_agent_all(paper_list, query, model1, model2, model3):
    await asyncio.gather(
        use_agent_first(paper_list, query, model1, 1, userPromptReason, systemPromptReason, Judge_List),
        use_agent_first(paper_list, query, model2, 2, userPromptNoReason, systemPromptNoReason, Judge_List)
    )
       
    # await use_agent_first(paper_list, query, model2, 2, userPromptNoReason, systemPromptNoReason, Judge_List_Reason),
    # await use_agent_first(paper_list, query, model1, 1, userPromptReason, systemPromptReason, Judge_List_NoReason),

    #Check whether Flag1 is eaqual to Flag2
    same_mask = paper_list["Flag1"].astype(str).str.strip().str.upper() == paper_list["Flag2"].astype(str).str.strip().str.upper()

    #If equal, copy the values in Flag1 to Flag3
    paper_list.loc[same_mask, "Flag3"] = paper_list.loc[same_mask, "Flag1"]
    
    #Get the different values
    ListAgent3 = paper_list.loc[~same_mask].to_dict("records")

    if ListAgent3:
        print(len(ListAgent3))
        await use_agent_after(paper_list, ListAgent3, query, model3) 

#Judge by agent1 and agent2
async def use_agent_first(paper_list, query, model, num, userPrompt, systemPrompt, Judge_List):
    agent = create_agent(
        model = model,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPrompt
    )
    response = await agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": userPrompt.format(query=query, paper_list=paper_list)
        }]
    })
    #print(response)
    result=response["structured_response"]
    response_list=[w.model_dump(exclude_none=True) for w in result.judge_list]
    print(response_list)
    CollectAIResponse(paper_list, response_list, num)
    print(f"Aagent{num} done")

#Judge by agent3
async def use_agent_after(paper_list, ListAgent3, query, model):
    agent = create_agent(
        model = model,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPromptReason
    )
    response = await agent.ainvoke({
        "messages": [{
            "role": "user",
            "content": userPromptReason.format(query=query, paper_list=ListAgent3)
        }]
    })
    result=response["structured_response"]
    response_list=[w.model_dump(exclude_none=True) for w in result.judge_list]
    #print(response_list)
    CollectAIResponse(paper_list, response_list, 3)
    print("Last agent done")

#Transform the AIResponse
def CollectAIResponse(paper_list, response, num):
    for e in response:
        id = e['ID']
        flag = e['Flag']
        paper_list.loc[paper_list['ID'] == id, f"Flag{num}"] = flag
        if (num == 3 or num == 1):
            reason = e['Reason']
            paper_list.loc[paper_list['ID'] == id, 'Reason'] = reason

async def main():
    #save_dir = input("enter address: ").strip()
    save_dir = r"C:\Users\erzhu\Desktop\GRP-MultiAgent\Screening"

    model1_name="gpt-4.1-mini"
    model2_name="gpt-4.1-mini"
    model3_name="gpt-4.1"

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

    await abstract_screening(
        save_dir,
        model1,
        model2,
        model3
    )

if __name__ == "__main__":
    asyncio.run(main())