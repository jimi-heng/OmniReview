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

# Limit components
# Max essays AI get in one time
batch_size = 30
# Max retry times when AI failed
retries = 3
# Max time(s) AI allowed to run. If out of this time, retry
timeout = 180
# Delay(s) between retries
delay = 3

systemPromptReason = """
    Role: 
        You are an expert biomedical literature evaluator specializing in evidence-based medicine and systematic reviews.
    Goal:
        Based on the provided PICO framework, research topic, and any extra requirements, determine whether a research paper is relevant.
    Instructions:
        1. Carefullly read the Topic, Abstract_clean, PICO information and Extra requirements(if have).
        2. Review the paper's title and abstract.
        3. Decide if the paper's content meaningfully fits the PICO question, Extra requirements and Topic.
        4. Matching Rules:
            Carefully match the Chinese PICO terms with the English paper content, considering synonyms and equivalent medical concepts.
            Population (P) Matching Rules:
                P is considered matched if:
                    P must be the main research object.
                    If the study provides a narrower, earlier, lighter, or otherwise partially overlapping version of the target condition 
                        (e.g., a younger subgroup within the target age, a lower dose within the acceptable range, or a subset of the intended population), 
                        treat it as consistent unless there is a clear contradiction.
                    There is no explicit contradiction with key descriptors,
                    Missing information on some population characteristics does not disqualify matching; it is treated as potentially include.
                P is not matched only if:
                    P is not the main research object.
                    The study explicitly contradicts PICO descriptors (e.g., subjects are outside the target age range or clearly have conditions excluded by PICO),
                    Key characteristics directly conflict with PICO requirements.
                    Does not satisfy any information
            Intervention (I) Matching Rules:
                I is considered matched if:
                    The intervention is the same in type or principle.
                    Ignore differences in dose, frequency, or duration.
                    Accept logical variants or clinically equivalent approaches.
                I is not matched only if:
                    The intervention is clearly unrelated.
            Comparison (C) Matching Rules:
                C is considered matched if:
                    Includes any relevant control or comparison group (e.g., placebo, usual care, no treatment, another treatment, before–after comparison).
                    Even if the control group is not identical, as long as it helps evaluate the intervention.
                C is not matched onlf if:
                    None of the reported outcomes are relevant.
            Outcome (O) Matching Rules:
                O is considered matched if:
                    The study measures or reports at least one outcome relevant to the target PICO.
                    Outcomes belong to the same logical domain (e.g., "clinical attachment level" and "periodontal regeneration parameters").
                O is not matched only if:
                    None of the reported outcomes are relevant.
            Extra requirements(If have):
                Extra requirements is considered mathed if:
                    The study satisfies at least one of the specified extra requirements.
                    Minor differences in measurement are acceptable.
                Extra information is not matched only if:
                    None of the extra requirements are met.
            Final Inclusion Rule (Flag):
                DO NOT give the final result only according to one components
                Count how many of P, I, C, O, Extra requirements are matched.
                Must judge every components and strictly follow the steps:
                    If at least five components match → Flag = 1 (Include). even if other components (e.g., Intervention or Comparison) are not present.
                    If fewer than five components match → Flag = 0 (Exclude).
        5. Your response must include:
            1. ID: the id of this paper.
            2. Flag: return 1 if include, 0 if exclude.
            3. Reason: a specifical explanation of which PICO componets are contained and why this essay was include or exclude. 
                following the format:
                “This paper studies [research topic], matching [component1] ([corresponding content1 in essay]) and [component2] ([corresponding content2 in essay]) PICO components.” 
                In Chinese
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
        Based on the provided PICO framework, research topic, and any extra requirements, determine whether a research paper is relevant (i.e., eligible for inclusion).
    Instructions:
        1. Carefullly read the Topic, Abstract_clean, PICO information and Extra requirements(if have).
        2. Review the paper's title and abstract.
        3. Decide if the paper's content meaningfully fits the PICO question, Extra requirements and Topic.
        4. Matching Rules:
            Carefully match the Chinese PICO terms with the English paper content, considering synonyms and equivalent medical concepts.
            Population (P) Matching Rules:
                P is considered matched if:
                    P must be the main research object.
                    If the study provides a narrower, earlier, lighter, or otherwise partially overlapping version of the target condition 
                        (e.g., a younger subgroup within the target age, a lower dose within the acceptable range, or a subset of the intended population), 
                        treat it as consistent unless there is a clear contradiction.
                    There is no explicit contradiction with key descriptors,
                    Missing information on some population characteristics does not disqualify matching; it is treated as potentially include.
                P is not matched only if:
                    P is not the main research object.
                    The study explicitly contradicts PICO descriptors (e.g., subjects are outside the target age range or clearly have conditions excluded by PICO),
                    Key characteristics directly conflict with PICO requirements.
                    Does not satisfy any information
            Intervention (I) Matching Rules:
                I is considered matched if:
                    The intervention is the same in type or principle.
                    Ignore differences in dose, frequency, or duration.
                    Accept logical variants or clinically equivalent approaches.
                I is not matched only if:
                    The intervention is clearly unrelated.
            Comparison (C) Matching Rules:
                C is considered matched if:
                    Includes any relevant control or comparison group (e.g., placebo, usual care, no treatment, another treatment, before–after comparison).
                    Even if the control group is not identical, as long as it helps evaluate the intervention.
                C is not matched onlf if:
                    None of the reported outcomes are relevant.
            Outcome (O) Matching Rules:
                O is considered matched if:
                    The study measures or reports at least one outcome relevant to the target PICO.
                    Outcomes belong to the same logical domain (e.g., "clinical attachment level" and "periodontal regeneration parameters").
                O is not matched only if:
                    None of the reported outcomes are relevant.
            Extra requirements(If have):
                Extra requirements is considered mathed if:
                    The study satisfies at least one of the specified extra requirements.
                    Minor differences in measurement are acceptable.
                Extra information is not matched only if:
                    None of the extra requirements are met.
            Final Inclusion Rule (Flag):
                Count how many of P, I, C, O, Extra requirements are matched.
                DO NOT give the final result only according to one components
                Must judge every components and strictly follow the steps:
                    If at least five components match → Flag = 1 (Include). even if other components (e.g., Intervention or Comparison) are not present.
                    If fewer than five components match → Flag = 0 (Exclude).
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
        2. Each PICO component (Population, Intervention, Comparison, Outcome) may contain multiple detailed requirements.
        3. A component is considered “matched” as long as the paper does NOT explicitly contradict any of its requirements.
        4. A paper is suitable (Flag=1) if it briefly matches five PICO components (Population, Intervention, Comparison, Outcome) and Extra reqiurements(if have).
        5. If fewer than five components match, Flag=0.
        6. Provide a short reasoning for each paper explaining which PICO components were matched. In Chinese
"""

userPromptNoReason = """
    PICO_Topic dictionary: 
        {query}
    Papers: 
        {paper_list}
    Task:
        1. Evaluate each paper independently.
        2. Each PICO component (Population, Intervention, Comparison, Outcome) may contain multiple detailed requirements.
        3. A component is considered “matched” as long as the paper does NOT explicitly contradict any of its requirements.
        4. A paper is suitable (Flag=1) if it briefly matches five PICO components (Population, Intervention, Comparison, Outcome) and Extra requirements(if have).
        5. If fewer than five components match, Flag=0.
        6. Provide a short reasoning for each paper explaining which PICO components were matched. In Chinese
"""

#The type of single value in the list
class Judge_Base(BaseModel):
    """Judge whether the essay is suitable"""
    ID: int = Field(..., description = "The ID of the eaasy")
    Flag: Literal["1", "0"] = Field(..., description = "the judge of whether the value is suitbale")
    Reason: Optional[str] = Field(None, description="the reason of the judge")

#The whole list
class Judge_List(BaseModel):
    """List of every essay's judge"""
    judge_list: List[Judge_Base] = Field(..., description="the list of each essay's judge")



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

# Retry when time out
async def call_with_retry(coro_func, *args):
    for attempt in range(retries):
        try:
            return await asyncio.wait_for(coro_func(*args), timeout)
        except asyncio.TimeoutError:
            print(f"Timeout after {timeout}s (attempt {attempt+1}/{retries}), retrying...")
        except Exception as e:
            print(f"Error: {e} (attempt {attempt+1}/{retries}), retrying...")
        await asyncio.sleep(delay)
    print(f"Failed after {retries} retries")
    return None

#Combine all the agents
async def use_agent_all(paper_list, query, model1, model2, model3):
    total = len(paper_list)

    agent1 = create_agent(
        model = model1,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPromptReason
    )
    agent2 = create_agent(
        model = model2,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPromptNoReason
    )
    agent3 = create_agent(
        model = model3,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPromptReason
    )

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_df = paper_list.iloc[start:end].copy()

        # use agent 1 and 2
        await asyncio.gather(
            call_with_retry(use_agent_first, agent1, batch_df, query, 1, userPromptReason),
            call_with_retry(use_agent_first, agent2, batch_df, query, 2, userPromptNoReason)
        )

        same_mask = (
            batch_df["Flag1"].astype(str).str.strip().str.upper()
            == batch_df["Flag2"].astype(str).str.strip().str.upper()
        )

        batch_df.loc[same_mask, "Flag3"] = batch_df.loc[same_mask, "Flag1"]

        diff_records = batch_df.loc[~same_mask].to_dict("records")

        if diff_records:
            print(f"Batch {start // batch_size + 1}: {len(diff_records)} need review by model3")
            await call_with_retry(use_agent_after,agent3, batch_df, diff_records, query)

        # write back the results
        paper_list.loc[start:end-1, ["Flag1", "Flag2", "Flag3", "Reason"]] = batch_df[["Flag1", "Flag2", "Flag3", "Reason"]]

        print(f"Batch {start // batch_size + 1} done\n")

        # a break
        await asyncio.sleep(3)
    return paper_list

#Judge by agent1 and agent2
async def use_agent_first(agent, paper_list, query, num, userPrompt):
    response = await agent.ainvoke(
        {
            "messages": [{
                "role": "user",
                "content": userPrompt.format(query=query, paper_list=paper_list)
            }]
        },
        configurable={"reset_context": True}
    )
    #print(response)
    result=response["structured_response"]
    response_list=[w.model_dump(exclude_none=True) for w in result.judge_list]
    #print(response_list)
    CollectAIResponse(paper_list, response_list, num)
    print(f"Aagent{num} done")

#Judge by agent3
async def use_agent_after(agent, paper_list, ListAgent3, query):
    response = await agent.ainvoke(
        {
            "messages": [{
                "role": "user",
                "content": userPromptReason.format(query=query, paper_list=ListAgent3)
            }]
        },
        configurable={"reset_context": True}
    )
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