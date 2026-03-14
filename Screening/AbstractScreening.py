import random

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
import asyncio
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

Entrez.email = "erzhuzi2023@outlook.com"

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")

model1_name = "gpt-4.1"
model2_name = "gpt-4.1-mini"
model3_name = "gpt-4.1"

whole_paper_list = []
topic_keywords = ""

reasonSystemPrompt = """
3. Reason:
A clear explanation in English, using the format:

“This paper studied [research topic]. It matched [component 1] (corresponding content in the text) and [component 2] (corresponding content in the text). 
It did not match [component 1] (corresponding content in the text) and [component 2] (corresponding content in the text). A total of n components were matched, therefore the paper was included/excluded.”
"""

reasonUserPrompt = """
7. Optionally provide a short reasoning in English listing which components are matched or not matched.
"""

PICOSsystemPromptNoReason = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Goal:
Determine whether a research paper is potentially relevant based on the provided SPIC framework 
(considering Study Design, Population, Intervention, and Comparison), the research title, and extra requirements (if any).

If the user provides Outcome (O) requirements, include Outcome in the evaluation. 
If Outcome is not provided, ignore Outcome completely.

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, SPIC information, Outcome (if provided), and Extra requirements (if provided).
2. Evaluate the paper using the SPIC framework: Study Design (S), Population (P), Intervention (I), and Comparison (C).
3. Evaluate Outcome (O) ONLY if it is provided by the user.
4. Match Chinese PICO terms with English content, allowing for synonyms and equivalent medical concepts.

Matching Rules:

Study Design (S):
- Matched if:
    - The study design corresponds to the required design (e.g., randomized controlled trial, cohort study, case-control study, cross-sectional study).
    - Minor variations or unclear descriptions are allowed if the design is likely compatible.
- Not matched if:
    - The study design is clearly different from the required type.
    - No study design information is mentioned.

Population (P):
- Matched if:
    - The population is the main research object.
    - The study includes a narrower or partially overlapping population without clear contradiction.
    - No explicit conflict with key population descriptors.
    - Missing details are allowed (treated as potentially included).
- Not matched if:
    - Population is not the main focus.
    - Explicit contradiction with SPIC population.
    - No relevant population information at all.
- IMPORTANT:
    - In abstract screening, population mismatch MUST NOT be used as a reason for exclusion.
    - Population matching status is for counting purposes only.

Intervention (I):
- Matched if:
    - Same or clinically equivalent intervention type or principle.
    - Differences in dose, frequency, or duration are ignored.
- Not matched if:
    - Intervention is clearly different or unrelated.
- IMPORTANT:
    - Intervention mismatch MUST NOT be used as a reason for exclusion.
    - Intervention matching status is for counting purposes only.

Comparison (C):
- Matched if:
    - Includes any relevant control or comparison group (e.g., placebo, usual care, no treatment, another treatment, before–after comparison).
    - Even if the control group is not identical, as long as it helps evaluate the intervention.
- Not matched if:
    - No comparison information is mentioned.
- IMPORTANT:
    - Comparison mismatch MUST NOT be used as a reason for exclusion.
    - Comparison matching status is for counting purposes only.

Outcome (O) – Only evaluate if provided:
- Matched if:
    - The study measures outcomes related to the user-specified outcome concept.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the reported outcomes relate to the specified outcome.

Extra Requirements (if any):
- Matched if:
    - At least one extra requirement is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the extra requirements are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Always evaluate: S, P, I, C
    - Evaluate O only if provided
    - Evaluate Extra if provided
- Count how many components are matched.
- Do NOT exclude a paper solely because Population or Intervention or Comparison does not match.
- If ≥ 2 components match → Flag = 1 (Include).
- If < 2 components match → Flag = 0 (Exclude).

Output Format (must include all):
1. ID: the paper ID.
2. Flag: 1 (Include) or 0 (Exclude).
"""

PICOSsystemPromptReason = PICOSsystemPromptNoReason + reasonSystemPrompt

PICOSuserPromptNoReason = """
 SPIC_Topic:
    {query}

Papers:
    {paper_list}

Task:
1. Independently evaluate each paper.

2. For each paper, evaluate the following components:
   - Study Design (S)
   - Population (P)
   - Intervention (I)
   - Comparison (C)

3. Outcome (O) should ONLY be evaluated if the user provides an Outcome requirement in the query.
   - If Outcome is not provided, completely ignore Outcome in both evaluation and counting.
   Extra requirements (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - S, P, I, C
   - Outcome (only if provided)
   - Extra requirements (if provided)

6. Inclusion rule:
   - If at least 2 components are matched → Flag = 1 (Include)
   - If fewer than 2 components are matched → Flag = 0 (Exclude)
"""

PICOSuserPromptReason = PICOSuserPromptNoReason + reasonUserPrompt


PECOsystemPromptNoReason = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Goal:
Determine whether a research paper is potentially relevant based on the provided PECO framework 
(considering Population, Exposure, Comparator, and Outcome), the research title, and extra requirements (if any).

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, PECO information, and Extra requirements (if provided).
2. Evaluate the paper using the PECO framework: Population (P), Exposure (E), Comparator (C), and Outcome (O).
3. Match Chinese PECO terms with English content, allowing for synonyms and equivalent medical concepts.

Matching Rules:

Population (P):
- Matched if:
    - The population is the main research object.
    - The study includes a narrower or partially overlapping population without clear contradiction.
    - No explicit conflict with key population descriptors.
    - Missing details are allowed (treated as potentially included).
- Not matched if:
    - Population is not the main focus.
    - Explicit contradiction with PECO population.
    - No relevant population information at all.
- IMPORTANT:
    - In abstract screening, population mismatch MUST NOT be used as a reason for exclusion.
    - Population matching status is for counting purposes only.

Exposure (E):
- Matched if:
    - The study investigates the specified exposure (e.g., environmental factor, risk factor, lifestyle exposure, biomarker, or other exposure of interest).
    - The exposure concept is the same or clinically equivalent.
- Not matched if:
    - The exposure is clearly different or unrelated.
- IMPORTANT:
    - Exposure mismatch MUST NOT be used as a reason for exclusion.
    - Exposure matching status is for counting purposes only.

Comparator (C):
- Matched if:
    - The study includes a comparison group or reference group (e.g., unexposed group, low exposure vs high exposure, control group, baseline comparison).
    - Even if the comparator is not identical, as long as it enables comparison of exposure effects.
- Not matched if:
    - No comparison or reference group is mentioned.
- IMPORTANT:
    - Comparator mismatch MUST NOT be used as a reason for exclusion.
    - Comparator matching status is for counting purposes only.

Outcome (O):
- Matched if:
    - The study measures outcomes related to the user-specified outcome concept.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the reported outcomes relate to the specified outcome.

Extra Requirements (if any):
- Matched if:
    - At least one extra requirement is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the extra requirements are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Population (P)
    - Exposure (E)
    - Comparator (C)
    - Outcome (O)
    - Extra (if provided)

- Count how many components are matched.
- Do NOT exclude a paper solely because Population or Exposure or Comparator does not match.

- If ≥ 2 components match → Flag = 1 (Include).
- If < 2 components match → Flag = 0 (Exclude).

Output Format (must include all):
1. ID: the paper ID.
2. Flag: 1 (Include) or 0 (Exclude).
"""

PECOsystemPromptReason = PECOsystemPromptNoReason + reasonSystemPrompt

PECOuserPromptNoReason = """
PECO_Topic:
    {query}

Papers:
    {paper_list}

Task:
1. Independently evaluate each paper.

2. For each paper, evaluate the following components:
   - Population (P)
   - Exposure (E)
   - Comparator (C)
   - Outcome (O)

3. Extra requirements (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - P, E, C, O
   - Extra requirements (if provided)

6. Inclusion rule:
   - If at least 2 components are matched → Flag = 1 (Include)
   - If fewer than 2 components are matched → Flag = 0 (Exclude)
"""

PECOuserPromptReason = PECOuserPromptNoReason + reasonUserPrompt


PIROsystemPromptNoReason = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Goal:
Determine whether a research paper is potentially relevant based on the provided PIRO framework 
(considering Population, Intervention, Response, and Outcome), the research title, and extra requirements (if any).

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, PIRO information, and Extra requirements (if provided).
2. Evaluate the paper using the PIRO framework: Population (P), Intervention (I), Response (R), and Outcome (O).
3. Match Chinese PIRO terms with English content, allowing for synonyms and equivalent medical concepts.

Matching Rules:

Population (P):
- Matched if:
    - The population is the main research object.
    - The study includes a narrower or partially overlapping population without clear contradiction.
    - No explicit conflict with key population descriptors.
    - Missing details are allowed (treated as potentially included).
- Not matched if:
    - Population is not the main focus.
    - Explicit contradiction with PIRO population.
    - No relevant population information at all.
- IMPORTANT:
    - Population mismatch MUST NOT be used as a reason for exclusion.
    - Population matching status is for counting purposes only.

Intervention (I):
- Matched if:
    - The study investigates the specified treatment, exposure, or management strategy.
    - The intervention concept is the same or clinically equivalent.
- Not matched if:
    - The intervention is clearly different or unrelated.
- IMPORTANT:
    - Intervention mismatch MUST NOT be used as a reason for exclusion.
    - Intervention matching status is for counting purposes only.

Response (R):
- Matched if:
    - The study evaluates a biological, physiological, or clinical response related to the intervention.
    - Minor measurement differences are acceptable.
- Not matched if:
    - No relevant response indicators are described.

Outcome (O):
- Matched if:
    - The study measures outcomes corresponding to the specified outcome concept.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the reported outcomes relate to the specified outcome.

Extra Requirements (if any):
- Matched if:
    - At least one extra requirement is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the extra requirements are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Population (P)
    - Intervention (I)
    - Response (R)
    - Outcome (O)
    - Extra (if provided)

- Count how many components are matched.
- Do NOT exclude a paper solely because Population or Intervention does not match.

- If ≥ 2 components match → Flag = 1 (Include).
- If < 2 components match → Flag = 0 (Exclude).

Output Format (must include all):
1. ID: the paper ID.
2. Flag: 1 (Include) or 0 (Exclude).
"""

PIROsystemPromptReason = PIROsystemPromptNoReason + reasonSystemPrompt

PIROuserPromptNoReason = """
PIRO_Topic:
    {query}

Papers:
    {paper_list}

Task:
1. Independently evaluate each paper.

2. For each paper, evaluate the following components:
   - Population (P)
   - Intervention (I)
   - Response (R)
   - Outcome (O)

3. Extra requirements (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - P, I, R, O
   - Extra requirements (if provided)

6. Inclusion rule:
   - If at least 2 components are matched → Flag = 1 (Include)
   - If fewer than 2 components are matched → Flag = 0 (Exclude)
"""

PIROuserPromptReason = PIROuserPromptNoReason + reasonUserPrompt


def save_file(paper_list):
    save_dir = Path(SCRIPT_DIR.parent / "resources")
    save_dir.mkdir(parents=True, exist_ok=True)
    filename = save_dir / "CSVList.csv"
    paper_list.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"保存到: {filename}")

async def abstract_screening():
    global topic_keywords

    population = input("Enter Population: ").strip()
    intervention = input("Enter Intervention: ").strip()
    comparison = input("Enter Comparison: ").strip()
    outcome = input("Enter Outcome: ").strip()

    query = {
        "Topic" : topic_keywords,
        "Population" : population,
        "Intervention" : intervention,
        "Comparison" : comparison,
        "Outcome" : outcome
    }

    paper_list = pd.DataFrame(whole_paper_list)
    await ThreeAgnets.use_agent_all(paper_list, query, model1_name, model2_name, model3_name, PICOSsystemPromptReason, PICOSsystemPromptNoReason,
                                    PICOSuserPromptReason, PICOSuserPromptNoReason)
    save_file(paper_list)


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
    paper_list = pd.DataFrame(whole_paper_list)
    save_file(paper_list)


# Upload files
def upload_to_csv():
    global whole_paper_list, topic_keywords
    file_dir = input("enter RIS file: ").strip()

async def main():
    # save_dir = input("enter address: ").strip()

    await abstract_screening()

def reconstruct_abstract(inv_index):
    """将 OpenAlex 的 abstract_inverted_index 还原为正常 abstract"""
    if not inv_index:
        return ""

    words = []
    for word, positions in inv_index.items():
        for pos in positions:
            words.append((pos, word))

    words.sort()
    return " ".join(word for _, word in words)

def search_openalex(query, max_number):

    try:
        url = "https://api.openalex.org/works"

        params = {
            "search": query,
            "filter": "has_abstract:true",
            "per-page": max_number
        }

        r = requests.get(url, params=params)

        if r.status_code != 200:
            print("OpenAlex request failed:", r.status_code)
            return []

        data = r.json()

        results = []

        for p in data.get("results", []):

            abstract = reconstruct_abstract(
                p.get("abstract_inverted_index")
            )
            if not abstract:
                continue

            # authors
            authors = []
            for a in p.get("authorships", []):
                author_info = a.get("author") or {}
                name = author_info.get("display_name")
                if name:
                    authors.append(name)

            author_str = "; ".join(authors)

            # journal（防止 None）
            primary_location = p.get("primary_location") or {}
            source = primary_location.get("source") or {}
            journal = source.get("display_name", "")

            # year
            year = p.get("publication_year") or ""

            # doi
            doi = p.get("doi") or ""
            doi = doi.replace("https://doi.org/", "")

            row = {
                "title": p.get("title") or "",
                "abstract": abstract or "",
                "author": author_str,
                "journal": journal,
                "year": year,
                "doi": doi
            }

            if not has_valid_abstract(row):
                continue

            results.append(row)
        return results

    except Exception as e:
        print(f"OpenAlex search error: {e}")
        return []

def extract_doi(record):
    """从 PubMed record 中提取 DOI"""
    for a in record.get("AID", []):
        if "[doi]" in a:
            return a.replace(" [doi]", "")
    return ""

def search_pubmed(query, max_number):

    try:
        # 搜索 PMID
        handle = Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=max_number
        )

        record = Entrez.read(handle)
        handle.close()

        pmids = record.get("IdList", [])

        if not pmids:
            return []

        # 获取详细信息
        handle = Entrez.efetch(
            db="pubmed",
            id=pmids,
            rettype="medline",
            retmode="text"
        )

        records = list(Medline.parse(handle))
        handle.close()

        results = []

        for r in records:

            # year
            year_str = r.get("DP", "")
            year = ""

            if year_str:
                try:
                    year = int(year_str[:4])
                except:
                    year = ""

            row = {
                "title": r.get("TI", "") or "",
                "abstract": r.get("AB", "") or "",
                "author": "; ".join(r.get("AU", [])),
                "journal": r.get("JT", "") or "",
                "year": year,
                "doi": extract_doi(r)
            }

            if not has_valid_abstract(row):
                continue
            results.append(row)

        return results

    except Exception as e:
        print(f"PubMed search error: {e}")
        return []

def literature_search_all(query, N):

    pubmed_papers = search_pubmed(query, N)
    openalex_papers = search_openalex(query, N)

    print(f"PubMed returned {len(pubmed_papers)} papers")
    print(f"OpenAlex returned {len(openalex_papers)} papers")

    all_papers = pubmed_papers + openalex_papers

    unique = {}
    results = []
    duplicate_count = 0

    for p in all_papers:

        doi = (p.get("doi") or "").lower().strip()

        # DOI 统一格式
        doi = doi.replace("https://doi.org/", "")

        if doi:
            key = doi
        else:
            key = p.get("title", "").lower()

        if key not in unique:
            unique[key] = True
            results.append(p)
        else:
            duplicate_count +=1

    # 打乱
    random.shuffle(results)

    # 取前 N
    results = results[:N]
    print(f"Final paper count: {len(results)}")
    print(f"Duplicate papers: {duplicate_count}")
    return results

def has_valid_abstract(paper):
    abstract = paper.get("abstract")

    if abstract is None:
        return False

    abstract = abstract.strip()

    if abstract == "":
        return False

    if abstract.lower() in ["no abstract available", "n/a"]:
        return False

    return True

# --- 新增对接接口开始 ---

# --- 新增对接接口开始 ---

async def _run_ai_screening_async(pico_data, papers, project_type='SPICO'):
    global model1_name, model2_name, model3_name
    global PICOSsystemPromptReason, PICOSsystemPromptNoReason, PICOSuserPromptReason, PICOSuserPromptNoReason
    global PECOsystemPromptReason, PECOsystemPromptNoReason, PECOuserPromptReason, PECOuserPromptNoReason
    global PIROsystemPromptReason, PIROsystemPromptNoReason, PIROuserPromptReason, PIROuserPromptNoReason
    global topic_keywords 
    
    results = []
    if not papers:
        return results
        
    # 动态匹配对应的 Prompt 模板
    if project_type == 'PECO':
        sys_reason = PECOsystemPromptReason
        sys_no_reason = PECOsystemPromptNoReason
        usr_reason = PECOuserPromptReason
        usr_no_reason = PECOuserPromptNoReason
    elif project_type == 'PIRO':
        sys_reason = PIROsystemPromptReason
        sys_no_reason = PIROsystemPromptNoReason
        usr_reason = PIROuserPromptReason
        usr_no_reason = PIROuserPromptNoReason
    else:
        sys_reason = PICOSsystemPromptReason
        sys_no_reason = PICOSsystemPromptNoReason
        usr_reason = PICOSuserPromptReason
        usr_no_reason = PICOSuserPromptNoReason

    # 将前端统一格式转化为 AI 识别的 Query 字典
    query = {
        "Topic": topic_keywords if 'topic_keywords' in globals() else "",
        "Study Design": pico_data.get("s", ""),
        "Population": pico_data.get('p', ''),
        "Intervention": pico_data.get('i', ""),
        "Exposure": pico_data.get('e', ""),
        "Comparator": pico_data.get('c', ""),
        "Comparison": pico_data.get('c', ""),
        "Index Test": pico_data.get('i', ""),
        "Reference Standard": pico_data.get('r', ""),
        "Response": pico_data.get('r', ""),
        "Outcome": pico_data.get('o', ''),
    }
    
    df_list = []
    for p in papers:
        df_list.append({
            'ID': p['id'],             
            'Title': p['title'],
            'Abstract_clean': p['abstract'],
            'Abstract': p['abstract'],
            'Flag1': '', 'Flag2': '', 'Flag3': '', 'Reason': ''               
        })
    paper_list_df = pd.DataFrame(df_list)
    
    try:
        updated_df = await ThreeAgnets.use_agent_all(
            paper_list_df, query, model1_name, model2_name, model3_name, 
            sys_reason, sys_no_reason, usr_reason, usr_no_reason
        )
        
        for index, row in updated_df.iterrows():
            flag_val = str(row.get('Flag3', '0')).strip()
            ai_decision = 'Included' if '1' in flag_val else 'Excluded'
            reason = str(row.get('Reason', ''))
            if not reason or reason.strip() == '' or reason == 'nan':
                reason = "AI successfully screened this paper but did not output detailed reasoning."
                
            results.append({'id': row['ID'], 'ai_decision': ai_decision, 'reasoning': reason})
            
    except Exception as e:
        print(f"ThreeAgnets Screening Error: {e}")
        for p in papers:
            results.append({'id': p['id'], 'ai_decision': 'Pending', 'reasoning': f"AI Screening Error: {str(e)}"})
            
    return results

def run_ai_screening_sync(pico_data, papers, project_type='SPICO'):
    """
    同步包装函数，新增 project_type 参数
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(_run_ai_screening_async(pico_data, papers, project_type))
        return results
    finally:
        loop.close()

# --- 新增对接接口结束 ---

if __name__ == "__main__":
    asyncio.run(main())
