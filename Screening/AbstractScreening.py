from Bio import Entrez
from Bio import Medline
import pandas as pd
import os
import re
import ThreeAgnets
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

Entrez.email = "erzhuzi2023@outlook.com"

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")

whole_paper_list = []
topic_keywords = ""

systemPromptReason = """
    Role:
        You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.
    
    Goal:
        Determine whether a research paper is potentially relevant based on the provided PICO framework (considering only Population, Intervention, Comparison and Extra requirements), research title, and extra requirements (if any).
    
    General Screening Principle (High Recall):
        - Default to inclusion unless there is an explicit contradiction.
        - Missing, unclear, or partially reported information should be treated as “potentially matched”.
        - Do NOT require explicit wording or complete reporting for a component to be considered matched.
        - Ignore Outcome (O) in this stage.
    
    Instructions:
    1. Read the Title, Abstract_clean, PICO information, and Extra requirements (if provided).
    2. Evaluate the paper using the PICO framework, but only for Population (P), Intervention (I), Comparison (C) and Extra requirements.
    3. Match Chinese PICO terms with English content, allowing for synonyms and equivalent medical concepts.
    
    Matching Rules:
    Population (P):
        - Matched if:
            - The population is the main research object.
            - The study includes a narrower or partially overlapping population without clear contradiction.
            - No explicit conflict with key population descriptors.
            - Missing details are allowed (treated as potentially included).
        - Not matched if:
            - Population is not the main focus.
            - Explicit contradiction with PICO population.
            - No relevant population information at all.
        - IMPORTANT:
            - In abstract screening, population mismatch MUST NOT be used as a reason for exclusion.
            - Population matching status is for counting purposes only.
    
    Intervention (I):
        - Matched if:
            - Same or clinically equivalent intervention type or principle.
            - Differences in dose, frequency, or duration are ignored.
        - Consider it not matched if:
            - Intervention is clearly different or unrelated.
        - IMPORTANT:
            - In abstract screening, intervention mismatch MUST NOT be used as a reason for exclusion.
            - Intervention matching status is for counting purposes only.
            
    Comparison (C) Matching Rules:
                - Matched if:
                    - Includes any relevant control or comparison group (e.g., placebo, usual care, no treatment, another treatment, before–after comparison).
                    - Even if the control group is not identical, as long as it helps evaluate the intervention.
                - Consider it not matched if:
                    - No comparison information is mentioned.
                - IMPORTANT:
                    - Comparison mismatch MUST NOT be used as a reason for exclusion.
                    - Comparison matching status is for counting purposes only.
    
    Extra Requirements (if any):
        - Matched if:
            - At least one extra requirement is satisfied.
            - Minor measurement differences are acceptable.
        - Not matched if:
            - None of the extra requirements are met.
    
    Final Inclusion Rule (Flag):
        - Evaluate the three components: P, I, C, Extra.
        - Count how many components are matched.
        - Do NOT exclude a paper solely because Population or Intervention or Comparison does not match.
        - If ≥ 2 component matches → Flag = 1 (Include).
        - If less than 2 components match → Flag = 0 (Exclude).
    
    Output Format (must include all):
    1. ID: the paper ID.
    2. Flag: 1 (Include) or 0 (Exclude).
    3. Reason: 
       A clear explanation in Chinese, using the format:
       “本文研究了[研究主题]，匹配了PICO中的[组件1]（文中对应内容）和[组件2]（文中对应内容），未匹配PICO中的[组件1](文中对应内容)和[组件2](文中对应内容)，总共匹配了n个PICO，因此被纳入/排除。”
    """

systemPromptNoReason = """
    Role:
        You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

    Goal:
        Determine whether a research paper is potentially relevant based on the provided PICO framework (considering only Population, Intervention, Comparison and Extra requirements), research title, and extra requirements (if any).

    General Screening Principle (High Recall):
        - Default to inclusion unless there is an explicit contradiction.
        - Missing, unclear, or partially reported information should be treated as “potentially matched”.
        - Do NOT require explicit wording or complete reporting for a component to be considered matched.
        - Ignore Outcome (O) in this stage.

    Instructions:
    1. Read the Title, Abstract_clean, PICO information, and Extra requirements (if provided).
    2. Evaluate the paper using the PICO framework, but only for Population (P), Intervention (I), Comparison (C) and Extra requirements.
    3. Match Chinese PICO terms with English content, allowing for synonyms and equivalent medical concepts.

    Matching Rules:
    Population (P):
        - Matched if:
            - The population is the main research object.
            - The study includes a narrower or partially overlapping population without clear contradiction.
            - No explicit conflict with key population descriptors.
            - Missing details are allowed (treated as potentially included).
        - Not matched if:
            - Population is not the main focus.
            - Explicit contradiction with PICO population.
            - No relevant population information at all.
        - IMPORTANT:
            - In abstract screening, population mismatch MUST NOT be used as a reason for exclusion.
            - Population matching status is for counting purposes only.

    Intervention (I):
        - Matched if:
            - Same or clinically equivalent intervention type or principle.
            - Differences in dose, frequency, or duration are ignored.
        - Consider it not matched if:
            - Intervention is clearly different or unrelated.
        - IMPORTANT:
            - In abstract screening, intervention mismatch MUST NOT be used as a reason for exclusion.
            - Intervention matching status is for counting purposes only.
            
    Comparison (C) Matching Rules:
                - Matched if:
                    - Includes any relevant control or comparison group (e.g., placebo, usual care, no treatment, another treatment, before–after comparison).
                    - Even if the control group is not identical, as long as it helps evaluate the intervention.
                - Consider it not matched if:
                    - No comparison information is mentioned.
                - IMPORTANT:
                    - Comparison mismatch MUST NOT be used as a reason for exclusion.
                    - Comparison matching status is for counting purposes only.

    Extra Requirements (if any):
        - Matched if:
            - At least one extra requirement is satisfied.
            - Minor measurement differences are acceptable.
        - Not matched if:
            - None of the extra requirements are met.

    Final Inclusion Rule (Flag):
        - Evaluate the three components: P, I, C, Extra.
        - Count how many components are matched.
        - Do NOT exclude a paper solely because Population or Intervention or Comparison does not match.
        - If ≥ 2 component matches → Flag = 1 (Include).
        - If less than 2 components match → Flag = 0 (Exclude).

    Output Format (must include all):
    1. ID: the paper ID.
    2. Flag: 1 (Include) or 0 (Exclude).
    """

userPromptReason = """
    PICO_Topic:
        {query}
    
    Papers:
        {paper_list}
    
    Task:
    1. Independently evaluate each paper.
    2. For each component, only consider Population (P), Intervention (I), Comparison (C) and Extra requirements.
       - A component is considered matched if the paper does NOT explicitly contradict its requirements.
       - Ignore Outcome (O) at this stage.
    3. Extra requirements (if any) are evaluated the same way.
    4. If at least 2 component (P, I, C or Extra) is matched → Flag = 1 (Include)
    5. If less than 2 components are matched → Flag = 0 (Exclude)
    6. Optionally, provide a short reasoning in Chinese, listing which components are matched.
"""

userPromptNoReason = """
    PICO_Topic:
        {query}

    Papers:
        {paper_list}

    Task:
    1. Independently evaluate each paper.
    2. For each component, only consider Population (P), Intervention (I), Comparison (C) and Extra requirements.
       - A component is considered matched if the paper does NOT explicitly contradict its requirements.
       - Ignore Outcome (O) at this stage.
    3. Extra requirements (if any) are evaluated the same way.
    4. If at least 2 component (P, I, C or Extra) is matched → Flag = 1 (Include)
    5. If less than 2 components are matched → Flag = 0 (Exclude)
"""


async def abstract_screening(save_dir, model1=None, model2=None, model3=None):
    global topic_keywords
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

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
    filename = save_dir / "CSVList.csv"
    await ThreeAgnets.use_agent_all(paper_list, pico1, model1, model2, model3, systemPromptReason, systemPromptNoReason,
                                    userPromptReason, userPromptNoReason)
    paper_list.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"保存到: {filename}")


# Download files from PubMed
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

    num = len(whole_paper_list)
    # Transform
    for idx, record in enumerate(records, start=0):
        row = {
            'ID': num + idx,
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


# Upload files
# def upload_to_csv():
#     global whole_paper_list, topic_keywords
#     file_dir = input("enter RIS file: ").strip()

# Get DOI
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
    # save_dir = input("enter address: ").strip()
    save_dir = SCRIPT_DIR

    model1_name = "gpt-4.1"
    model2_name = "gpt-4.1-mini"
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

    await abstract_screening(
        save_dir,
        model1,
        model2,
        model3
    )


if __name__ == "__main__":
    asyncio.run(main())
