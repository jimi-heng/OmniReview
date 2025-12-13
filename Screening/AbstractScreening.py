from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
import re
import ThreeAgnets
import asyncio
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
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

async def abstract_screening(save_dir, model1=None, model2=None, model3=None):
    global topic_keywords

    literature_search()

    # choice = 0
    # while True:
    #     print("Download files: 1, Upload files: 2")
    #     choice = int(input("Please choose: "))
    #     if (choice == 1):
    #         download_to_csv()
    #     elif choice == 2:
    #         upload_to_csv()
    #     elif choice == 3:
    #         break
    #     else:
    #         print("invalid number")
    #         continue

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
    await ThreeAgnets.use_agent_all(paper_list, pico1, model1, model2, model3, systemPromptReason, systemPromptNoReason, userPromptReason, userPromptNoReason)
    paper_list=paper_list.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"保存到: {filename}")

#Download files from PubMed
def literature_search():
    global whole_paper_list, topic_keywords
    
    query = input("enter key words: ").strip()
    topic_keywords = query + " " + topic_keywords
    max_number = input("enter max number: ").strip()

    # Search for pubmed List
    handle = Entrez.esearch(db="pubmed", term=query, retmax=max_number)
    record = Entrez.read(handle)
    handle.close()
    
    pmids = record["IdList"]
    print(f"find {len(pmids)} papers")
    
    if not pmids:
        return
    
    handle = Entrez.efetch(db="pubmed", id=pmids, rettype="medline", retmode="text")
    records = list(Medline.parse(handle))
    handle.close()

    num=len(whole_paper_list)
    # Transform
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
    print("\nExample of first paper:")
    print(whole_paper_list[0])

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

async def main():
    #save_dir = input("enter address: ").strip()
    save_dir = r"C:\Users\erzhu\Desktop\GRP-MultiAgent\Screening"

    model1_name="claude-haiku-4-5-20251001"
    model2_name="claude-haiku-4-5-20251001"
    model3_name="glm-4.6"

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