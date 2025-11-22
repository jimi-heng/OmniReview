from Bio import Entrez
import os
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain.tools import tool
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from typing import List

load_dotenv(override=True)

Entrez.email = "erzhuzi2023@outlook.com"
key1 = os.getenv("DMX_API_KEY_1")

@tool
def get_weather(location: str) -> str:
    """Get weather information for a location"""
    return f"Weather in {location}: Sunny, 72°F"

# 定义每个城市信息的数据结构
class Weather_Base(BaseModel):
    city: str = Field(..., description="The name of the city")
    degree: str = Field(..., description="The degree of the city")

# 定义一个列表形式的结构
class Weather_List(BaseModel):
    weathers: List[Weather_Base] = Field(..., description="List of weather info for cities")

# 创建模型
model1 = ChatOpenAI(
    model="claude-sonnet-4-20250514",
    base_url="https://www.dmxapi.cn/v1",
    api_key=key1,
    temperature =0
)

# 用 ToolStrategy 指定返回结构
agent = create_agent(
    model=model1,
    tools=[get_weather],
    response_format=ToolStrategy(Weather_List)
)

# 调用 agent
response = agent.invoke({
    "messages": [{"role": "user", "content": "What is the weather in London and Beijing"}]
})

print(response)
# 输出结构化响应
result = response["structured_response"]

# 转成列表（list of dict）
weather_list = [w.model_dump() for w in result.weathers]

print(weather_list)
