# Author: Team 04
# This file is developed by our team

import pandas as pd
import os
from Screening.abstract_screening import ThreeAgents
from Screening.abstract_screening.literature_search import literature_search_all
from pathlib import Path
from dotenv import load_dotenv
import asyncio


__all__ = ["run_ai_screening_sync"]


SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR / ".env", override=True)

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")

model1_name = "claude-haiku-4-5-20251001"
model2_name = "claude-haiku-4-5-20251001"
model3_name = "glm-4.6"

whole_paper_list = []
topic_keywords = ""


async def _run_ai_screening_async(pico_data, papers, project_type='SPICO'):
    """
    Run asynchronous AI-based abstract screening using multi-agent consensus.

    This function dynamically selects the appropriate prompt templates
    (SPICO / PECO / PIRO) and processes a list of papers using a
    three-agent evaluation pipeline.

    Args:
        pico_data (dict):
            Structured query data containing screening criteria such as:
            - s: Study Design
            - p: Population
            - i/e: Intervention or Exposure
            - c/r: Comparison or Reference
            - o: Outcome
            - es: Additional criteria

        papers (list[dict]):
            List of paper metadata. Each paper should contain:
            - id
            - title
            - abstract

        project_type (str, optional):
            Screening framework to use. Supported values:
            - 'SPICO' (default)

    Returns:
        list[dict]:
            Screening results with:
            - id (paper ID)
            - ai_decision ("Included" / "Excluded" / "Pending")
            - reasoning (text explanation)
    """

    global model1_name, model2_name, model3_name
    global PICOSsystemPromptReason, PICOSsystemPromptNoReason, PICOSuserPromptReason, PICOSuserPromptNoReason
    global PECOsystemPromptReason, PECOsystemPromptNoReason, PECOuserPromptReason, PECOuserPromptNoReason
    global PIROsystemPromptReason, PIROsystemPromptNoReason, PIROuserPromptReason, PIROuserPromptNoReason
    global topic_keywords

    results = []
    if not papers:
        return results

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

        query = {
            "Topic": topic_keywords if 'topic_keywords' in globals() else "",
            "Study Design": pico_data.get('s', ''),
            "Population": pico_data.get('p', ''),
            "Intervention": pico_data.get('i', ''),
            "Comparison": pico_data.get('c', ''),
            "Outcome": pico_data.get('o', ''),
            "Addition Criteria": pico_data.get('es', ''),
        }

    df_list = [
        {
            'ID': p['id'],
            'Title': p['title'],
            'Abstract_clean': p['abstract'],
            'Abstract': p['abstract'],
            'Flag1': '',
            'Flag2': '',
            'Flag3': '',
            'Reason': ''
        }
        for p in papers
    ]

    paper_list_df = pd.DataFrame(df_list)

    try:
        updated_df = await ThreeAgents.use_agent_all(
            paper_list_df,
            query,
            model1_name,
            model2_name,
            model3_name,
            sys_reason,
            sys_no_reason,
            usr_reason,
            usr_no_reason
        )

        for _, row in updated_df.iterrows():
            flag_val = str(row.get('Flag3', '0')).strip()
            ai_decision = 'Included' if '1' in flag_val else 'Excluded'

            reason = str(row.get('Reason', ''))
            if not reason or reason.strip() == '' or reason == 'nan':
                reason = "AI successfully screened this paper but did not output detailed reasoning."

            results.append({
                'id': row['ID'],
                'ai_decision': ai_decision,
                'reasoning': reason
            })

    except Exception as e:
        print(f"ThreeAgents Screening Error: {e}")
        for p in papers:
            results.append({
                'id': p['id'],
                'ai_decision': 'Pending',
                'reasoning': f"AI Screening Error: {str(e)}"
            })

    return results


def run_ai_screening_sync(pico_data, papers, project_type='SPICO'):
    """
    Synchronous wrapper for AI-based abstract screening.

    This function provides a blocking interface for the asynchronous
    screening pipeline.

    Args:
        pico_data (dict):
            Structured screening criteria (same format as async function).

        papers (list[dict]):
            List of paper metadata.

        project_type (str, optional):
            Screening framework:
            - 'SPICO'

    Returns:
        list[dict]:
            Screening results identical to `_run_ai_screening_async`.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        return loop.run_until_complete(
            _run_ai_screening_async(pico_data, papers, project_type)
        )
    finally:
        loop.close()