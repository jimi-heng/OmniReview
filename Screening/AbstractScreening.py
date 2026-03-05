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
       A clear explanation in English, using the format:
       “This paper studied the [research topic] and matched [component 1] (corresponding content in the text) and [component 2] (corresponding content in the text) in PICO. It did not match [component 1] (corresponding content in the text) and [component 2] (corresponding content in the text) in PICO. A total of n PICOs were matched, therefore they were included/excluded.”
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
    6. Optionally, provide a short reasoning in English, listing which components are matched.
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

    pico1 = {
        "Topic": "Wound Healing Rate",
        "Population": "Adults with acute wounds or surgical incisions",
        "Intervention": "Application of medical-grade honey dressings (e.g., Manuka honey)",
        "Comparison": "Standard wound care (e.g., saline or silver dressings)",
        "Outcome": "Shorter wound healing time (faster recovery)"
    }

    paper_list = pd.DataFrame(whole_paper_list)
    await ThreeAgnets.use_agent_all(paper_list, query, model1_name, model2_name, model3_name, systemPromptReason, systemPromptNoReason,
                                    userPromptReason, userPromptNoReason)
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

# Get DOI
def extract_doi(record):
    doi_pattern = re.compile(r"10\.\d{4,9}/[^\s\]]+", re.IGNORECASE)
    for key in ("LID", "AID"):
        val = record.get(key)
        if not val:
            continue
        text = " ".join(val) if isinstance(val, list) else str(val)
        match = doi_pattern.search(text)
        if match:
            return match.group(0)
    return ""

async def main():
    # save_dir = input("enter address: ").strip()

    await abstract_screening()

def search_pubmed(query, max_number):
    try:
        # 1. 搜索获取文献 ID 列表
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_number)
        record = Entrez.read(handle)
        handle.close()

        pmids = record.get("IdList", [])
        if not pmids:
            return []  # 没搜到就返回空列表

        # 2. 根据 ID 抓取文献详细信息
        handle = Entrez.efetch(db="pubmed", id=pmids, rettype="medline", retmode="text")
        records = list(Medline.parse(handle))
        handle.close()

        # 3. 格式化并返回结果
        results = []
        for record in records:
            # 尝试提取发表年份
            year_str = record.get('DP', '')
            year = None
            if year_str:
                # 取前 4 位作为年份
                try:
                    year = int(year_str[:4])
                except ValueError:
                    year = None

            row = {
                'title': record.get('TI', ''),
                'abstract': record.get('AB', ''),
                'author': '; '.join(record.get('AU', [])),
                'journal': record.get('JT', ''),
                'year': year,
                'doi': extract_doi(record),
                'keywords': '; '.join(record.get('OT', record.get('MH', [])))
            }
            results.append(row)
            
        return results
    except Exception as e:
        print(f"PubMed search error: {e}")
        return []
    

# --- 新增对接接口开始 ---

async def _run_ai_screening_async(pico_data, papers):
    # 1. 引入文件顶部定义好的全局 Prompt 和模型变量
    global model1_name, model2_name, model3_name
    global systemPromptReason, systemPromptNoReason, userPromptReason, userPromptNoReason
    global topic_keywords 
    
    results = []
    if not papers:
        return results
        
    # 2. 组装 ThreeAgnets 期望的 query 字典
    query = {
        "Topic": topic_keywords if 'topic_keywords' in globals() else "",
        "Population": pico_data.get('population', ''),
        "Intervention": pico_data.get('intervention', ''),
        "Comparison": pico_data.get('comparison', ''),
        "Outcome": pico_data.get('outcome', '')
    }
    
    # 3. 将后端传来的 SQLite 数据转换为你们期望的 DataFrame
    df_list = []
    for p in papers:
        df_list.append({
            'ID': p['id'],             # 【核心】：列名必须大写 ID，ThreeAgnets 内部使用它来定位行
            'Title': p['title'],
            'Abstract_clean': p['abstract'],
            'Abstract': p['abstract'],
            'Flag1': '',
            'Flag2': '',
            'Flag3': '',               # 仲裁后的最终结果会存放在 Flag3
            'Reason': ''               # 最终的推理理由
        })
    paper_list_df = pd.DataFrame(df_list)
    
    try:
        # 4. 调用你们的终极多智能体函数！传入完整的 9 个参数
        updated_df = await ThreeAgnets.use_agent_all(
            paper_list_df, 
            query, 
            model1_name, 
            model2_name, 
            model3_name, 
            systemPromptReason, 
            systemPromptNoReason,
            userPromptReason, 
            userPromptNoReason
        )
        
        # 5. 读取被 ThreeAgnets 写入了最终判定的 DataFrame，准备返回给数据库
        for index, row in updated_df.iterrows():
            # 按照你们的逻辑，最终结果一定在 Flag3 中（如果1和2一致，Flag3=Flag1；如果不一致，Agent3会写入Flag3）
            flag_val = str(row.get('Flag3', '0')).strip()
            ai_decision = 'Included' if '1' in flag_val else 'Excluded'
            
            # 获取推导理由
            reason = str(row.get('Reason', ''))
            if not reason or reason.strip() == '' or reason == 'nan':
                reason = "AI successfully screened this paper but did not output detailed reasoning."
                
            results.append({
                'id': row['ID'],
                'ai_decision': ai_decision,
                'reasoning': reason
            })
            
    except Exception as e:
        print(f"ThreeAgnets Screening Error: {e}")
        # 若大模型调用出错，保留 Pending 并返回错误信息
        for p in papers:
            results.append({
                'id': p['id'],
                'ai_decision': 'Pending',
                'reasoning': f"AI Screening Error: {str(e)}"
            })
            
    return results

def run_ai_screening_sync(pico_data, papers):
    """
    同步包装函数，供 app.py 在普通的 Flask 路由中调用
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(_run_ai_screening_async(pico_data, papers))
        return results
    finally:
        loop.close()
# --- 新增对接接口结束 ---


if __name__ == "__main__":
    asyncio.run(main())
