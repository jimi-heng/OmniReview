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

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


systemPromptReason = """
Role:
    You are an expert biomedical literature evaluator specializing in evidence-based medicine and systematic reviews.
Goal:
    Given a PICO (Population, Intervention, Comparison, Outcome) description and a Topic,
    your task is to determine whether a provided research paper is relevant (i.e., suitable for inclusion)
    or not relevant based on how well the paper aligns with the PICO and Topic.
Instructions:
    1. Carefully read the Topic and PICO information.
    2. Review the paper's full text content provided.
    3. Decide if the paper's content meaningfully fits the PICO question and Topic.
    4. Evaluate relevance using the following rules:
        1) The paper must clearly match ALL FOUR PICO components (Population, Intervention, Comparison, Outcome).
    5. Your response must include:
        1) ID: the id of this paper.
        2) Flag: return 1 if include, 0 if exclude.
        3) Reason: a brief explanation of which PICO components are contained and why this paper was included/excluded (in Chinese).
PICO description:
    1. Population (P): The study targets the same or a similar group of patients/subjects.
    2. Intervention (I): The main intervention matches or closely relates to that in the PICO.
    3. Comparison (C): The study includes a relevant control or comparison group (if applicable).
    4. Outcome (O): The study measures or reports on the same or relevant outcomes.
"""

userPromptReason = """
PICO:
Population (P): 铁缺乏但尚未贫血的儿童(0-6岁), 合并疾病?
Intervention (I): 铁剂治疗(每日2 mg/kg元素铁的口服铁剂治疗,疗程为12周),剂量,疗程
Comparison (C): 不进行铁剂治疗
Outcome (O): Critical:血色素水平, 贫血的发生率, 生长发育指标;
            Important: 安全性指标：胃肠道反应、食欲下降, 神经认知发育, 肠道菌群, 感染性疾病患病率
Extra requirements: Study design: SR、RCT、观察性研究

Papers (full text):
    {paper_list}
Task:
    1. Evaluate each paper independently.
    2. A paper is suitable (Flag=1) ONLY IF it matches ALL FOUR PICO components (P/I/C/O).
    3. If any component is missing/unclear, Flag=0.
    4. Provide a short reasoning for each paper explaining each PICO component (matched or missing) (in Chinese).
"""

batch_size = 6
retries = 3
timeout = 180
delay = 3


class Judge_Base(BaseModel):
    ID: int = Field(..., description="The ID of the paper")
    Flag: Literal["1", "0"] = Field(..., description="1 include, 0 exclude")
    Reason: Optional[str] = Field(None, description="Reason in Chinese")


class Judge_List(BaseModel):
    judge_list: List[Judge_Base] = Field(..., description="List of judgments")


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


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_pdf_text(pdf_path: Path) -> tuple[str, str]:
    reader = PdfReader(str(pdf_path))
    meta_title = ""
    try:
        if reader.metadata and reader.metadata.title:
            meta_title = str(reader.metadata.title).strip()
    except Exception:
        meta_title = ""

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            parts.append(page_text)
    return ("\n\n".join(parts), meta_title)


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def load_fulltext_from_resources(resources_dir: Path) -> pd.DataFrame:
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources folder not found: {resources_dir}")

    supported_exts = {".pdf", ".txt", ".md"}
    files = sorted(
        [p for p in resources_dir.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts],
        key=lambda p: str(p).lower(),
    )

    rows: list[dict] = []
    for idx, path in enumerate(files):
        title = path.stem
        full_text = ""
        error = ""

        try:
            if path.suffix.lower() == ".pdf":
                full_text, meta_title = _extract_pdf_text(path)
                if meta_title:
                    title = meta_title
            else:
                full_text = _read_text_file(path)
        except Exception as e:
            error = str(e)

        normalized = _normalize_text(full_text)
        preview = normalized[:500] if normalized else ""

        rows.append(
            {
                "ID": idx,
                "FileName": path.name,
                "RelativePath": str(path.relative_to(PROJECT_DIR)),
                "Title": title,
                "FullTextPreview": preview,
                "FullTextChars": len(normalized),
                "ReadError": error,
                "FullText": normalized,
                "Flag": "",
                "Reason": "",
            }
        )

    return pd.DataFrame(rows)


def write_fulltexts_to_txt(paper_df: pd.DataFrame, output_txt: Path) -> None:
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
    paper_df = load_fulltext_from_resources(resources_dir)
    if paper_df.empty:
        print(f"No supported files found in: {resources_dir}")
        return

    write_fulltexts_to_txt(paper_df, output_txt)
    print(f"Saved full texts: {output_txt}")

    agent = create_agent(
        model=model,
        response_format=ToolStrategy(Judge_List),
        system_prompt=systemPromptReason,
    )

    unreadable_mask = paper_df["ReadError"].astype(str).str.strip().ne("")
    paper_df.loc[unreadable_mask, "Flag"] = "0"
    paper_df.loc[unreadable_mask, "Reason"] = (
        "无法读取全文（读取错误），默认排除。错误信息："
        + paper_df.loc[unreadable_mask, "ReadError"].astype(str)
    )

    async def _judge_batch(batch_records: list[dict]) -> list[dict] | None:
        response = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": userPromptReason.format(paper_list=batch_records),
                    }
                ]
            },
            configurable={"reset_context": True},
        )
        result = response["structured_response"]
        return [w.model_dump(exclude_none=True) for w in result.judge_list]

    valid_ids = paper_df.loc[~unreadable_mask, "ID"].tolist()
    for start in range(0, len(valid_ids), batch_size):
        batch_ids = valid_ids[start : start + batch_size]
        batch_df = paper_df.loc[paper_df["ID"].isin(batch_ids), ["ID", "Title", "RelativePath", "FullText"]].copy()
        batch_records = batch_df.to_dict("records")

        judged = await call_with_retry(_judge_batch, batch_records)
        if not judged:
            print(f"Batch {start // batch_size + 1}: failed, leaving empty results")
            continue

        for e in judged:
            pid = e.get("ID")
            if pid is None:
                continue
            paper_df.loc[paper_df["ID"] == pid, "Flag"] = str(e.get("Flag", "")).strip()
            paper_df.loc[paper_df["ID"] == pid, "Reason"] = str(e.get("Reason", "")).strip()

        print(f"Batch {start // batch_size + 1} done")
        await asyncio.sleep(1)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result_df = paper_df.drop(columns=["FullText"])
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Saved: {output_csv}")


def _build_model(model_name: str, base_url: str) -> ChatOpenAI:
    key1 = os.getenv("DMX_API_KEY_1")
    if not key1:
        raise RuntimeError("Missing env var in Screening/.env: DMX_API_KEY_1")
    return ChatOpenAI(model=model_name, base_url=base_url, api_key=key1, temperature=0) # type: ignore


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Standalone full-text screening from files in ./resources")
    parser.add_argument("--resources-dir", type=Path, default=PROJECT_DIR / "resources")
    parser.add_argument("--output-csv", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_screening_results.csv")
    parser.add_argument("--output-txt", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_sent_to_ai.txt")
    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1")
    parser.add_argument("--model", type=str, default="glm-4.6")
    return parser.parse_args()


async def main() -> None:
    load_dotenv(SCRIPT_DIR / ".env", override=True)

    args = _parse_args()

    model = _build_model(args.model, base_url=args.base_url)
    await full_text_screening(
        resources_dir=args.resources_dir,
        output_csv=args.output_csv,
        output_txt=args.output_txt,
        model=model,
    )


if __name__ == "__main__":
    asyncio.run(main())
