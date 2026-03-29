import asyncio
import os
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from typing import Literal, List, Optional
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
load_dotenv(SCRIPT_DIR.parent / ".env", override=True)

key1 = os.getenv("DMX_API_KEY_1")
key2 = os.getenv("DMX_API_KEY_2")

#: Maximum number of papers processed per batch
batch_size = 20

#: Maximum retry attempts when a request fails
retries = 3

#: Timeout (seconds) for each async call
timeout = 180

#: Delay (seconds) between retries
delay = 3


class Judge_Base(BaseModel):
    """
    Schema for a single paper evaluation result.

    Attributes:
        ID: Unique identifier of the paper.
        Flag: Classification result ("1" = included, "0" = excluded).
        Reason: Optional explanation for the decision.
    """
    ID: int = Field(..., description="The ID of the essay")
    Flag: Literal["1", "0"] = Field(..., description="Classification result")
    Reason: Optional[str] = Field(None, description="Reason for the decision")


class Judge_List(BaseModel):
    """
    Container for a batch of evaluation results.

    Attributes:
        judge_list: List of `Judge_Base` items.
    """
    judge_list: List[Judge_Base] = Field(..., description="List of evaluation results")


async def call_with_retry(coro_func, *args):
    """
    Execute an async function with retry and timeout handling.

    Args:
        coro_func: Coroutine function to execute.
        *args: Arguments passed to the coroutine.

    Returns:
        Result of the coroutine, or None if all retries fail.
    """
    for attempt in range(retries):
        try:
            return await asyncio.wait_for(coro_func(*args), timeout)
        except asyncio.TimeoutError:
            print(f"Timeout after {timeout}s (attempt {attempt + 1}/{retries}), retrying...")
        except Exception as e:
            print(f"Error: {e} (attempt {attempt + 1}/{retries}), retrying...")
        await asyncio.sleep(delay)

    print(f"Failed after {retries} retries")
    return None


async def use_agent_all(
    paper_list,
    query,
    model1_name,
    model2_name,
    model3_name,
    systemPromptReason,
    systemPromptNoReason,
    userPromptReason,
    userPromptNoReason
):
    """
    Run a three-agent evaluation pipeline on a dataset.

    Workflow:
        1. Agent1 and Agent2 independently evaluate each batch.
        2. If results agree → directly accepted.
        3. If results differ → Agent3 performs final review.

    Args:
        paper_list: DataFrame containing papers.
        query: Query string (e.g., PICO JSON).
        model1_name: Model name for agent1.
        model2_name: Model name for agent2.
        model3_name: Model name for agent3.
        systemPromptReason: System prompt with reasoning.
        systemPromptNoReason: System prompt without reasoning.
        userPromptReason: User prompt with reasoning.
        userPromptNoReason: User prompt without reasoning.

    Returns:
        Updated DataFrame with Flag1, Flag2, Flag3, and Reason.
    """
    total = len(paper_list)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        batch_df = paper_list.iloc[start:end].copy()

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

        agent1 = create_agent(
            model=model1,
            response_format=ToolStrategy(Judge_List),
            system_prompt=systemPromptReason
        )
        agent2 = create_agent(
            model=model2,
            response_format=ToolStrategy(Judge_List),
            system_prompt=systemPromptNoReason
        )
        agent3 = create_agent(
            model=model3,
            response_format=ToolStrategy(Judge_List),
            system_prompt=systemPromptReason
        )

        # Run agent1 and agent2 concurrently
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
            await call_with_retry(use_agent_after, agent3, batch_df, diff_records, query, userPromptReason)

        paper_list.loc[start:end - 1, ["Flag1", "Flag2", "Flag3", "Reason"]] = batch_df[
            ["Flag1", "Flag2", "Flag3", "Reason"]
        ]

        print(f"Batch {start // batch_size + 1} done\n")

        await asyncio.sleep(3)

    return paper_list


async def use_agent_first(agent, paper_list, query, num, userPrompt):
    """
    Run initial evaluation using agent1 or agent2.

    Args:
        agent: LLM agent instance.
        paper_list: Batch DataFrame.
        query: Query string.
        num: Agent identifier (1 or 2).
        userPrompt: Prompt template.

    Updates:
        Writes results into Flag1 or Flag2 column.
    """
    response = await agent.ainvoke(
        {
            "messages": [{
                "role": "user",
                "content": userPrompt.format(query=query, paper_list=paper_list)
            }]
        },
        configurable={"reset_context": True}
    )

    result = response["structured_response"]
    response_list = [w.model_dump(exclude_none=True) for w in result.judge_list]

    CollectAIResponse(paper_list, response_list, num)
    print(f"Agent{num} done")


async def use_agent_after(agent, paper_list, ListAgent3, query, userPromptReason):
    """
    Run final evaluation using agent3 for conflicting cases.

    Args:
        agent: LLM agent instance.
        paper_list: Batch DataFrame.
        ListAgent3: Subset of conflicting records.
        query: Query string.
        userPromptReason: Prompt template with reasoning.

    Updates:
        Writes final decision into Flag3 and Reason.
    """
    response = await agent.ainvoke(
        {
            "messages": [{
                "role": "user",
                "content": userPromptReason.format(query=query, paper_list=ListAgent3)
            }]
        },
        configurable={"reset_context": True}
    )

    result = response["structured_response"]
    response_list = [w.model_dump(exclude_none=True) for w in result.judge_list]

    CollectAIResponse(paper_list, response_list, 3)
    print("Agent3 done")


def CollectAIResponse(paper_list, response, num):
    """
    Map agent responses back to the DataFrame.

    Args:
        paper_list: DataFrame containing papers.
        response: List of response dictionaries.
        num: Agent identifier (1, 2, or 3).

    Updates:
        Writes Flag{num} and Reason into the DataFrame.
    """
    for e in response:
        id = e['ID']
        flag = e['Flag']

        paper_list.loc[paper_list['ID'] == id, f"Flag{num}"] = flag

        if num == 3 or num == 1:
            reason = e['Reason']
            paper_list.loc[paper_list['ID'] == id, 'Reason'] = reason