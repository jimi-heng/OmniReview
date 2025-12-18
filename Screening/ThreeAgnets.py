import asyncio
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# Limit components
# Max essays AI get in one time
batch_size = 20
# Max retry times when AI failed
retries = 3
# Max time(s) AI allowed to run. If out of this time, retry
timeout = 180
# Delay(s) between retries
delay = 3

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
async def use_agent_all(paper_list, query, model1, model2, model3, systemPromptReason, systemPromptNoReason, userPromptReason, userPromptNoReason):
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
            await call_with_retry(use_agent_after,agent3, batch_df, diff_records, query, userPromptReason)

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
async def use_agent_after(agent, paper_list, ListAgent3, query, userPromptReason):
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
        if num == 3 or num == 1:
            reason = e['Reason']
            paper_list.loc[paper_list['ID'] == id, 'Reason'] = reason
