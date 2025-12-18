"""
全文本文献筛选脚本
基于PICO标准和AI模型对生物医学文献进行相关性筛选
"""

import argparse
import asyncio
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from pypdf import PdfReader
from typing import Literal, List, Optional

# 脚本所在目录和项目根目录
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# 系统提示词：定义AI评审员的角色和任务要求
systemPromptReason = """
    Role: 
        You are an expert biomedical literature evaluator specializing in evidence-based medicine and systematic reviews.
    Goal:
        Based on the provided PICO framework, research topic, and any extra requirements, determine whether a research paper is relevant.
    Instructions:
        1. Carefully read the Topic, Abstract_clean, PICO information and Extra requirements(if have).
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
                C is not matched only if:
                    None of the reported outcomes are relevant.
            Outcome (O) Matching Rules:
                O is considered matched if:
                    The study measures or reports at least one outcome relevant to the target PICO.
                    Outcomes belong to the same logical domain (e.g., "clinical attachment level" and "periodontal regeneration parameters").
                O is not matched only if:
                    None of the reported outcomes are relevant.
            Extra requirements(If have):
                Extra requirements is considered matched if:
                    The study satisfies at least one of the specified extra requirements.
                    Minor differences in measurement are acceptable.
                Extra information is not matched only if:
                    None of the extra requirements are met.
            Final Inclusion Rule (Flag):
                DO NOT give the final result only according to one components
                Count how many of P, I, C, O, Extra requirements are matched.
                Must judge every components and strictly follow the steps:
                    If at least 4 components match → Flag = 1 (Include). even if other components (e.g., Intervention or Comparison) are not present.
                    If fewer than 4 components match → Flag = 0 (Exclude).
        5. Your response must include:
            1. ID: the id of this paper.
            2. Flag: return 1 if include, 0 if exclude.
            3. Reason: a specifical explanation of which PICO components are contained and why this essay was include or exclude. 
                following the format:
                “This paper studies [research topic], matching [component1] ([corresponding content1 in essay]) and [component2] ([corresponding content2 in essay]) PICO components.” 
                In Chinese
    PICO description:
        1. Population (P): The study targets the same or a similar group of patients/subjects.
        2. Intervention (I): The main intervention matches or closely relates to that in the PICO.
        3. Comparison (C): The study includes a relevant control or comparison group (if applicable).
        4. Outcome (O): The study measures or reports on the same or relevant outcomes.
"""

# 用户提示词：具体的PICO标准和任务说明
userPromptReason = """
PICO:
Population (P): 铁缺乏但尚未贫血的儿童(0-6岁), 合并疾病?
Intervention (I): 铁剂治疗(每日2 mg/kg元素铁的口服铁剂治疗,疗程为12周),剂量,疗程
Comparison (C): 不进行铁剂治疗
Outcome (O): Critical:血色素水平, 贫血的发生率, 生长发育指标;
            Important: 安全性指标：胃肠道反应、食欲下降, 神经认知发育, 肠道菌群, 感染性疾病患病率
Extra requirements: Study design: SR、RCT、观察性研究

Papers: 
        {paper_list}
    Task:
        1. Evaluate each paper independently.
        2. Each PICO component (Population, Intervention, Comparison, Outcome) may contain multiple detailed requirements.
        3. A component is considered “matched” as long as the paper does NOT explicitly contradict any of its requirements.
        4. A paper is suitable (Flag=1) if it briefly matches 4 PICO components (Population, Intervention, Comparison, Outcome) and Extra reqiurements(if have).
        5. If fewer than 4 components match, Flag=0.
        6. Provide a short reasoning for each paper explaining which PICO components were matched. In Chinese
"""

# 批处理参数配置
batch_size = 6  # 每批处理的文献数量
retries = 3  # API调用重试次数
timeout = 180  # API调用超时时间（秒）
delay = 3  # 重试间隔时间（秒）


class Judge_Base(BaseModel):
    """单篇文献的评审结果数据模型"""
    ID: int = Field(..., description="文献的唯一标识ID")
    Flag: Literal["1", "0"] = Field(..., description="1表示纳入，0表示排除")
    Reason: Optional[str] = Field(None, description="中文说明的评审理由")


class Judge_List(BaseModel):
    """批量评审结果的数据模型"""
    judge_list: List[Judge_Base] = Field(..., description="评审结果列表")


async def call_with_retry(coro_func, *args):
    """带重试机制的异步调用包装器

    Args:
        coro_func: 要执行的异步函数
        *args: 函数的参数

    Returns:
        函数执行结果，失败时返回None
    """
    for attempt in range(retries):
        try:
            # 设置超时限制执行函数
            return await asyncio.wait_for(coro_func(*args), timeout)
        except asyncio.TimeoutError:
            print(f"Timeout after {timeout}s (attempt {attempt + 1}/{retries}), retrying...")
        except Exception as e:
            print(f"Error: {e} (attempt {attempt + 1}/{retries}), retrying...")
        await asyncio.sleep(delay)  # 重试前等待
    print(f"Failed after {retries} retries")
    return None


def _normalize_text(text: str) -> str:
    """清理和规范化文本

    Args:
        text: 原始文本

    Returns:
        清理后的标准化文本
    """
    text = text.replace("\x00", "")  # 移除空字符
    text = re.sub(r"[ \t]+", " ", text)  # 合并连续空格和制表符
    text = re.sub(r"\n{3,}", "\n\n", text)  # 合并过多换行
    return text.strip()


def _extract_pdf_text(pdf_path: Path) -> tuple[str, str]:
    """从PDF文件中提取文本内容

    Args:
        pdf_path: PDF文件路径

    Returns:
        tuple[正文文本, 元数据标题]
    """
    reader = PdfReader(str(pdf_path))
    meta_title = ""
    try:
        # 尝试提取PDF元数据中的标题
        if reader.metadata and reader.metadata.title:
            meta_title = str(reader.metadata.title).strip()
    except Exception:
        meta_title = ""

    parts: list[str] = []
    # 逐页提取文本
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            parts.append(page_text)
    return ("\n\n".join(parts), meta_title)


def _read_text_file(path: Path) -> str:
    """读取纯文本文件内容

    Args:
        path: 文本文件路径

    Returns:
        文件内容字符串
    """
    return path.read_text(encoding="utf-8", errors="ignore")


def load_fulltext_from_resources(resources_dir: Path) -> pd.DataFrame:
    """从资源目录加载所有文献全文

    Args:
        resources_dir: 资源目录路径

    Returns:
        包含文献信息的DataFrame
    """
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources folder not found: {resources_dir}")

    # 支持的文件格式
    supported_exts = {".pdf", ".txt", ".md"}
    # 递归查找所有支持的文件
    files = sorted(
        [p for p in resources_dir.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts],
        key=lambda p: str(p).lower(),
    )

    rows: list[dict] = []
    for idx, path in enumerate(files):
        title = path.stem  # 默认使用文件名（不含扩展名）作为标题
        full_text = ""
        error = ""

        try:
            # 根据文件类型调用不同的解析方法
            if path.suffix.lower() == ".pdf":
                full_text, meta_title = _extract_pdf_text(path)
                if meta_title:
                    title = meta_title  # 优先使用PDF元数据中的标题
            else:
                full_text = _read_text_file(path)
        except Exception as e:
            error = str(e)  # 记录读取错误

        # 标准化文本内容
        normalized = _normalize_text(full_text)
        preview = normalized[:500] if normalized else ""  # 截取前500字符作为预览

        # 构建文献记录
        rows.append(
            {
                "ID": idx,  # 自动分配的ID
                "FileName": path.name,
                "RelativePath": str(path.relative_to(PROJECT_DIR)),
                "Title": title,
                "FullTextPreview": preview,
                "FullTextChars": len(normalized),
                "ReadError": error,
                "FullText": normalized,  # 完整的标准化文本
                "Flag": "",  # 等待AI评审填充
                "Reason": "",  # 等待AI评审填充
            }
        )

    return pd.DataFrame(rows)


def write_fulltexts_to_txt(paper_df: pd.DataFrame, output_txt: Path) -> None:
    """将文献全文写入文本文件（用于调试和记录）

    Args:
        paper_df: 文献DataFrame
        output_txt: 输出文本文件路径
    """
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    with output_txt.open("w", encoding="utf-8") as f:
        for row in paper_df.to_dict("records"):
            f.write("=" * 80 + "\n")
            f.write(f"ID: {row.get('ID')}\n")
            f.write(f"FileName: {row.get('FileName')}\n")
            f.write(f"RelativePath: {row.get('RelativePath')}\n")
            f.write(f"Title: {row.get('Title')}\n")
            f.write(f"FullTextChars: {row.get('FullTextChars')}\n")
            f.write(f"ReadError: {row.get('ReadError')}\n")
            f.write("-" * 80 + "\n")
            f.write((row.get("FullText") or "") + "\n")
            f.write("\n")


async def full_text_screening(
        resources_dir: Path,
        output_csv: Path,
        output_txt: Path,
        model: ChatOpenAI,
) -> None:
    """执行全文本筛选的主函数

    Args:
        resources_dir: 文献资源目录
        output_csv: 输出CSV文件路径
        output_txt: 输出文本文件路径
        model: AI模型实例
    """
    # 1. 加载文献全文
    paper_df = load_fulltext_from_resources(resources_dir)
    if paper_df.empty:
        print(f"No supported files found in: {resources_dir}")
        return

    # 2. 将全文写入文本文件（供参考）
    write_fulltexts_to_txt(paper_df, output_txt)
    print(f"Saved full texts: {output_txt}")

    # 3. 创建AI代理
    agent = create_agent(
        model=model,
        response_format=ToolStrategy(Judge_List),  # 指定结构化输出格式
        system_prompt=systemPromptReason,
    )

    # 4. 标记无法读取的文献（自动排除）
    unreadable_mask = paper_df["ReadError"].astype(str).str.strip().ne("")
    paper_df.loc[unreadable_mask, "Flag"] = "0"
    paper_df.loc[unreadable_mask, "Reason"] = (
            "无法读取全文（读取错误），默认排除。错误信息："
            + paper_df.loc[unreadable_mask, "ReadError"].astype(str)
    )

    async def _judge_batch(batch_records: list[dict]) -> list[dict] | None:
        """评审一批文献

        Args:
            batch_records: 批处理文献记录列表

        Returns:
            评审结果列表，失败时返回None
        """
        # 调用AI代理进行评审
        response = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": userPromptReason.format(paper_list=batch_records),
                    }
                ]
            },
            configurable={"reset_context": True},  # 每次调用重置上下文
        )
        result = response["structured_response"]
        # 转换为字典格式
        return [w.model_dump(exclude_none=True) for w in result.judge_list]

    # 5. 分批处理可读文献
    valid_ids = paper_df.loc[~unreadable_mask, "ID"].tolist()
    for start in range(0, len(valid_ids), batch_size):
        batch_ids = valid_ids[start: start + batch_size]
        # 提取批处理需要的字段
        batch_df = paper_df.loc[paper_df["ID"].isin(batch_ids), ["ID", "Title", "RelativePath", "FullText"]].copy()
        batch_records = batch_df.to_dict("records")

        # 调用评审函数（带重试）
        judged = await call_with_retry(_judge_batch, batch_records)
        if not judged:
            print(f"Batch {start // batch_size + 1}: failed, leaving empty results")
            continue

        # 6. 更新评审结果到DataFrame
        for e in judged:
            pid = e.get("ID")
            if pid is None:
                continue
            paper_df.loc[paper_df["ID"] == pid, "Flag"] = str(e.get("Flag", "")).strip()
            paper_df.loc[paper_df["ID"] == pid, "Reason"] = str(e.get("Reason", "")).strip()

        print(f"Batch {start // batch_size + 1} done")
        await asyncio.sleep(1)  # 批处理间隔

    # 7. 保存结果到CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result_df = paper_df.drop(columns=["FullText"])  # 移除全文内容以减小文件大小
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")  # 支持中文的编码
    print(f"Saved: {output_csv}")


def _build_model(model_name: str, base_url: str) -> ChatOpenAI:
    """构建AI模型实例

    Args:
        model_name: 模型名称
        base_url: API基础URL

    Returns:
        配置好的ChatOpenAI实例
    """
    key1 = os.getenv("DMX_API_KEY_1")
    if not key1:
        raise RuntimeError("Missing env var in Screening/.env: DMX_API_KEY_1")
    return ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=key1,
        temperature=0  # 设置为0以确保结果确定性
    )  # type: ignore


def _parse_args() -> argparse.Namespace:
    """解析命令行参数

    Returns:
        包含解析后参数的命名空间
    """
    parser = argparse.ArgumentParser(description="Standalone full-text screening from files in ./resources")
    parser.add_argument("--resources-dir", type=Path, default=PROJECT_DIR / "resources", help="文献资源目录")
    parser.add_argument("--output-csv", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_screening_results.csv",
                        help="输出CSV文件路径")
    parser.add_argument("--output-txt", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_sent_to_ai.txt",
                        help="输出文本文件路径")
    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1", help="API基础URL")
    parser.add_argument("--model", type=str, default="glm-4.6", help="AI模型名称")
    return parser.parse_args()


async def main() -> None:
    """主异步函数"""
    # 加载环境变量
    load_dotenv(SCRIPT_DIR / ".env", override=True)

    args = _parse_args()

    # 构建模型
    model = _build_model(args.model, base_url=args.base_url)

    # 执行全文本筛选
    await full_text_screening(
        resources_dir=args.resources_dir,
        output_csv=args.output_csv,
        output_txt=args.output_txt,
        model=model,
    )


if __name__ == "__main__":
    # 运行主异步函数
    asyncio.run(main())
