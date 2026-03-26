import pandas as pd
import os
from Screening.abstract_screening import ThreeAgents
from pathlib import Path
from dotenv import load_dotenv
import asyncio

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")

model1_name = "claude-haiku-4-5-20251001"
model2_name = "claude-haiku-4-5-20251001"
model3_name = "glm-4.6"

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
(considering Study Design, Population, Intervention, and Comparison), the research title, and additional criteria (if any).

If the user provides Outcome (O) requirements, include Outcome in the evaluation. 
If Outcome is not provided, ignore Outcome completely.

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, SPIC information, Outcome (if provided), and Additional Criteria (if provided).
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

Additional Criteria (if any):
- Matched if:
    - At least one additional criteria is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the additional criteria are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Always evaluate: S, P, I, C
    - Evaluate O only if provided
    - Evaluate Extra if provided
- Count how many components are matched.
- Do NOT exclude a paper solely because Population or Intervention or Comparison does not match.
- If ≥ 3 components match → Flag = 1 (Include).
- If < 3 components match → Flag = 0 (Exclude).

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
   Additional Criteria (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - S, P, I, C
   - Outcome (only if provided)
   - Additional Criteria (if provided)

6. Inclusion rule:
   - If at least 3 components are matched → Flag = 1 (Include)
   - If fewer than 3 components are matched → Flag = 0 (Exclude)
"""

PICOSuserPromptReason = PICOSuserPromptNoReason + reasonUserPrompt

PECOsystemPromptNoReason = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

Goal:
Determine whether a research paper is potentially relevant based on the provided PECO framework 
(considering Population, Exposure, Comparison, and Outcome), the research title, and additional criteria (if any).

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, PECO information, and Additional Criteria (if provided).
2. Evaluate the paper using the PECO framework: Population (P), Exposure (E), Comparison (C), and Outcome (O).
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

Comparison (C):
- Matched if:
    - The study includes a comparison group or reference group (e.g., unexposed group, low exposure vs high exposure, control group, baseline comparison).
    - Even if the comparison is not identical, as long as it enables comparison of exposure effects.
- Not matched if:
    - No comparison or reference group is mentioned.
- IMPORTANT:
    - Comparison mismatch MUST NOT be used as a reason for exclusion.
    - Comparison matching status is for counting purposes only.

Outcome (O):
- Matched if:
    - The study measures outcomes related to the user-specified outcome concept.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the reported outcomes relate to the specified outcome.

Additional Criteria (if any):
- Matched if:
    - At least one extra requirement is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the additional criteria are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Population (P)
    - Exposure (E)
    - Comparison (C)
    - Outcome (O)
    - Additional Criteria (if provided)

- Count how many components are matched.
- Do NOT exclude a paper solely because Population or Exposure or Comparison does not match.

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
   - Comparison (C)
   - Outcome (O)

3. Additional Criteria (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - P, E, C, O
   - Additional Criteria (if provided)

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
(considering Population, Indicator, Reference, and Outcome), the research title, and additional ariteria (if any).

General Screening Principle (High Recall):
- Default to inclusion unless there is an explicit contradiction.
- Missing, unclear, or partially reported information should be treated as “potentially matched”.
- Do NOT require explicit wording or complete reporting for a component to be considered matched.

Instructions:
1. Read the Title, Abstract_clean, PIRO information, and Additional Criteria (if provided).
2. Evaluate the paper using the PIRO framework: Population (P), Indicator (I), Reference (R), and Outcome (O).
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

Indicator (I)

- Matched if:
    - The study investigates the specified indicator, such as a clinical indicator, biomarker, diagnostic measure, physiological measure, or risk indicator.
    - The indicator concept is the same or clinically equivalent.
- Not matched if:
    - The indicator is clearly different or unrelated.
- IMPORTANT:
    - Indicator mismatch MUST NOT be used as a reason for exclusion.
    - Indicator matching status is for counting purposes only.

Response (R):
- Matched if:
    - The study includes a reference group, baseline group, control group, or comparative benchmark.
    - Even if the reference is not identical, as long as it enables comparison of indicator effects..
- Not matched if:
    - No reference or comparison group is mentioned.

Outcome (O):
- Matched if:
    - The study measures outcomes corresponding to the specified outcome concept.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the reported outcomes relate to the specified outcome.

Additional Criteria (if any):
- Matched if:
    - At least one additional criteria is satisfied.
    - Minor measurement differences are acceptable.
- Not matched if:
    - None of the additional criteria are met.

Final Inclusion Rule (Flag):
- Evaluate the following components:
    - Population (P)
    - Intervention (I)
    - Response (R)
    - Outcome (O)
    - Additional Criteria (if provided)

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
   - Indicator (I)
   - Reference (R)
   - Outcome (O)

3. Additional Criteria (if any) should also be evaluated.

4. Matching rule:
   - A component is considered matched if the paper does NOT explicitly contradict the requirement.
   - Missing, vague, or partially reported information should be treated as potentially matched.

5. Count the number of matched components among:
   - P, I, R, O
   - Additional Criteria (if provided)

6. Inclusion rule:
   - If at least 2 components are matched → Flag = 1 (Include)
   - If fewer than 2 components are matched → Flag = 0 (Exclude)
"""

PIROuserPromptReason = PIROuserPromptNoReason + reasonUserPrompt


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

        query = {
            "Topic": topic_keywords if 'topic_keywords' in globals() else "",
            "Population": pico_data.get('p', ''),
            "Exposure": pico_data.get('e', ''),
            "Comparison": pico_data.get('c', ''),
            "Outcome": pico_data.get('o', ''),
            "Addition Criteria": pico_data.get('es', ''),
        }

    elif project_type == 'PIRO':
        sys_reason = PIROsystemPromptReason
        sys_no_reason = PIROsystemPromptNoReason
        usr_reason = PIROuserPromptReason
        usr_no_reason = PIROuserPromptNoReason

        # 将前端统一格式转化为 AI 识别的 Query 字典
        query = {
            "Topic": topic_keywords if 'topic_keywords' in globals() else "",
            "Population": pico_data.get('p', ''),
            "Indicator": pico_data.get('i', ''),
            "Reference": pico_data.get('r', ''),
            "Outcome": pico_data.get('o', ''),
            "Addition Criteria": pico_data.get('es', ''),
        }

    else:
        sys_reason = PICOSsystemPromptReason
        sys_no_reason = PICOSsystemPromptNoReason
        usr_reason = PICOSuserPromptReason
        usr_no_reason = PICOSuserPromptNoReason

        # 将前端统一格式转化为 AI 识别的 Query 字典
        query = {
            "Topic": topic_keywords if 'topic_keywords' in globals() else "",
            "Study Design": pico_data.get('s', ''),
            "Population": pico_data.get('p', ''),
            "Intervention": pico_data.get('i', ''),
            "Comparison": pico_data.get('c', ''),
            "Outcome": pico_data.get('o', ''),
            "Addition Criteria": pico_data.get('es', ''),
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
        updated_df = await ThreeAgents.use_agent_all(
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
