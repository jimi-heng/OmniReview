"""
基于AI的全文文献筛选脚本（纯视觉模式）
用于根据 PICO 标准自动筛选生物医学文献。
仅支持 PDF 输入，并以 PDF 页面图像作为论文内容来源（适用于包含表格/图片的全文）。
"""

import argparse
import asyncio
import base64
import os
import re
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing import Literal, List, Optional

# 尝试导入PyMuPDF用于PDF处理
try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

# 路径配置
SCRIPT_DIR = Path(__file__).resolve().parent  # 脚本所在目录
PROJECT_DIR = SCRIPT_DIR.parent  # 项目根目录

# 系统提示词 - 定义AI的角色和任务
systemPromptReason = """
Role:
You are an expert in biomedical literature evaluation, specializing in evidence-based medicine and systematic reviews.

IMPORTANT CONTEXT:
- You will receive ONLY PDF page images.
- You MUST base all judgments strictly on visible content in the images.
- Tables and figures are valid evidence.
- Do NOT assume missing information.
- Do NOT infer unstated details.
- If something is not explicitly visible in the PDF images, treat it as Not Matched.

Screening Type:
This is FULL-TEXT screening (not abstract screening).

Component Evaluation Rules:

Population (P):
- Matched ONLY if explicit textual evidence supports the target population.
- If information is missing → Not Matched.
- If explicitly contradictory → Not Matched.

Intervention (I):
- Matched ONLY if iron supplementation therapy is explicitly described.
- Variations in dose/duration acceptable.
- If not explicitly described → Not Matched.

Comparison (C):
- Matched ONLY if a comparator group is explicitly described.
- If no comparator described → Not Matched.

Outcome (O):
- Matched ONLY if at least one required outcome is explicitly reported.
- If no relevant outcome explicitly reported → Not Matched.

Extra Requirements:
- Matched ONLY if satisfied the extra reqiurements
- If not satisfied → Not Matched.

Final Inclusion Rule:
- Count matched components among P, I, C, O, Extra.
- If ≥4 components are Matched → Flag = 1.
- If <4 components are Matched → Flag = 0.

CRITICAL Evidence Extraction Rule:
- For every component marked as Matched = Yes, you MUST extract exact original text from the PDF.
- The extracted text must be character-by-character identical.
- The output must be a single continuous span of text 
- Do NOT combine multiple sentences 
- Do NOT paraphrase.
- Do NOT summarize.
- Do NOT translate.
- Do NOT modify punctuation.
- Extract continuous visible text only.
- If Matched = No, Evidence MUST be empty ("").

STRICT FORMAT ENFORCEMENT:
- You MUST output ALL five components.
- You MUST NOT omit any section.
- You MUST NOT provide explanations outside the template.
- You MUST NOT explain why something is Not Matched.
- Output ONLY in the required template.
- If format is violated, regenerate internally before answering.
    """

# 用户提示词 - 具体的PICO标准和任务
userPromptReason = """
PICO:

Population (P):
Iron deficiency without anemia in children aged 0–6 years.

Intervention (I):
Oral iron supplementation therapy.
Reference: 2 mg/kg/day elemental iron for 12 weeks.
(Dose and duration variations acceptable.)

Comparison (C):
No iron supplementation.

Outcome (O):

Critical:
- Hemoglobin level
- Incidence of anemia
- Growth and developmental indicators

Important:
- Gastrointestinal reactions
- Appetite loss
- Neurocognitive development
- Gut microbiota
- Infectious disease incidence

Extra Requirements:
Study design must be:
- Systematic Review (SR)
- Randomized Controlled Trial (RCT)
- Observational study

Input Format:
You will receive PDF page images labeled:
"Paper ID <ID> - PDF Page <page_number>:"

Use ONLY the images to judge.

Task:
1. Evaluate each paper independently.
2. Evaluate P, I, C, O, Extra separately.
3. No inference beyond visible text.
4. Apply ≥4 component rule.
5. Extract exact evidence for matched components.

STRICT OUTPUT TEMPLATE (NO EXTRA TEXT):

ID: <Paper ID>
Flag: 0 or 1

Reason:
Population:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Intervention:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Comparison:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Outcome:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"

Extra:
Matched: Yes/No
Evidence: "<exact copied text or empty string>"
"""

# 默认参数配置
batch_size = 6  # 默认批量大小
retries = 3  # 重试次数
timeout = 180  # 超时时间（秒）
delay = 3  # 重试延迟（秒）


# 数据模型定义 - 单篇文献的判断结果
class Judge_Base(BaseModel):
    """单篇文献的判断结果数据结构"""
    ID: int = Field(..., description="文献ID")
    Flag: Literal["1", "0"] = Field(..., description="1表示纳入，0表示排除")
    Reason: Optional[str] = Field(None, description="判断理由(一字不差的原文)")


# 数据模型定义 - 批量文献的判断结果列表
class Judge_List(BaseModel):
    """批量文献判断结果的数据结构"""
    judge_list: List[Judge_Base] = Field(..., description="判断结果列表")


async def call_with_retry(coro_func, *args):
    """
    带重试机制的异步调用函数

    Args:
        coro_func: 要执行的协程函数
        *args: 函数参数

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
    """
    规范化文本内容

    Args:
        text: 原始文本

    Returns:
        规范化后的文本
    """
    text = text.replace("\x00", "")  # 移除空字符
    text = re.sub(r"[ \t]+", " ", text)  # 合并连续空格和制表符
    text = re.sub(r"\n{3,}", "\n\n", text)  # 合并过多换行
    return text.strip()


def _extract_pdf_metadata_with_pymupdf(pdf_path: Path) -> tuple[str, int]:
    """
    使用PyMuPDF提取PDF元数据（仅用于视觉模式）

    Args:
        pdf_path: PDF文件路径

    Returns:
        tuple: (标题, 页数)

    Raises:
        RuntimeError: 当PyMuPDF未安装时
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for PDF metadata in vision-only mode. Install `pymupdf`.")

    with fitz.open(str(pdf_path)) as doc:
        meta_title = ""
        try:
            meta_title = str((doc.metadata or {}).get("title") or "").strip()
        except Exception:
            meta_title = ""
        return meta_title, int(doc.page_count)


def _parse_page_spec(spec: str) -> list[int] | None:
    """
    解析页面规格字符串

    Args:
        spec: 页面规格字符串，如 "all", "1-3,5", "1,2,3"

    Returns:
        页面编号列表，None表示全部页面
    """
    spec = (spec or "").strip()
    if not spec:
        return []
    if spec.lower() in {"all", "*"}:
        return None

    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            # 处理页码范围，如 "1-3"
            start_s, end_s = part.split("-", 1)
            start = int(start_s.strip())
            end = int(end_s.strip())
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start  # 确保起始小于结束
            pages.update(range(start, end + 1))
        else:
            # 处理单页
            page = int(part)
            if page > 0:
                pages.add(page)
    return sorted(pages)


def _pdf_pages_to_data_urls(
        pdf_path: Path,
        pages: list[int] | None,
        *,
        dpi: int,
        image_format: str,
        jpeg_quality: int,
) -> list[tuple[int, str]]:
    """
    将PDF页面转换为base64编码的data URL图像

    Args:
        pdf_path: PDF文件路径
        pages: 要转换的页面列表，None表示所有页面
        dpi: 图像分辨率
        image_format: 图像格式（jpeg/png/webp）
        jpeg_quality: JPEG质量（1-100）

    Returns:
        列表，每个元素为(页码, data_url)

    Raises:
        RuntimeError: 当PyMuPDF未安装时
        ValueError: 当图像格式不支持时
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for vision PDF input. Install `pymupdf`.")

    fmt = (image_format or "").lower().strip()
    if fmt not in {"png", "jpeg", "webp"}:
        raise ValueError(f"Unsupported image format: {image_format}")

    with fitz.open(str(pdf_path)) as doc:
        page_count = doc.page_count
        if pages is None:
            selected = list(range(1, page_count + 1))  # 所有页面
        else:
            selected = [p for p in pages if 1 <= p <= page_count]  # 过滤有效页面

        out: list[tuple[int, str]] = []
        for page_number in selected:
            page = doc.load_page(page_number - 1)  # PyMuPDF页面索引从0开始
            pix = page.get_pixmap(dpi=dpi, alpha=False)  # 生成位图

            # 根据格式编码图像
            if fmt == "png":
                img_bytes = pix.tobytes("png")
                mime = "image/png"
            elif fmt == "webp":
                img_bytes = pix.tobytes(output="webp")
                mime = "image/webp"
            else:
                img_bytes = pix.tobytes(output="jpeg", jpg_quality=int(jpeg_quality))
                mime = "image/jpeg"

            # 生成data URL
            b64 = base64.b64encode(img_bytes).decode("ascii")
            out.append((page_number, f"data:{mime};base64,{b64}"))
        return out


def load_fulltext_from_resources(resources_dir: Path) -> pd.DataFrame:
    """
    从资源目录加载文献信息（纯视觉模式）

    Args:
        resources_dir: 资源目录路径

    Returns:
        包含文献信息的DataFrame

    Raises:
        FileNotFoundError: 当资源目录不存在时
    """
    resources_dir = resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources folder not found: {resources_dir}")

    # 支持的文件扩展名
    supported_exts = {".pdf"}
    # 递归查找所有支持的文件
    files = sorted(
        [p for p in resources_dir.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts],
        key=lambda p: str(p).lower(),
    )

    rows: list[dict] = []
    for idx, path in enumerate(files):
        path = path.resolve()
        title = path.stem  # 默认使用文件名作为标题
        full_text = ""
        num_pages = 0
        error = ""

        try:
            meta_title, num_pages = _extract_pdf_metadata_with_pymupdf(path)
            if meta_title:
                title = meta_title
            full_text = ""  # 纯视觉模式下不提取文本
        except Exception as e:
            error = str(e)  # 记录错误信息

        # 规范化文本
        normalized = _normalize_text(full_text)
        preview = normalized[:500] if normalized else ""  # 预览前500字符

        # 构建记录
        rows.append(
            {
                "ID": idx,  # 自动分配ID
                "FileName": path.name,
                "RelativePath": str(path.relative_to(PROJECT_DIR)) if PROJECT_DIR in path.parents else str(path),
                "Suffix": path.suffix.lower(),
                "Title": title,
                "FullTextPreview": preview,
                "FullTextChars": len(normalized),
                "NumPages": num_pages,
                "ReadError": error,
                "FullText": normalized,
                "Flag": "",  # 待填充：筛选结果
                "Reason": "",  # 待填充：筛选理由
            }
        )

    return pd.DataFrame(rows)


def write_fulltexts_to_txt(paper_df: pd.DataFrame, output_txt: Path) -> None:
    """
    将文献信息写入文本文件（用于调试和记录）

    纯视觉模式下不会提取/写入PDF全文文本，FullText字段将为空。

    Args:
        paper_df: 文献DataFrame
        output_txt: 输出文本文件路径
    """
    output_txt.parent.mkdir(parents=True, exist_ok=True)
    with output_txt.open("w", encoding="utf-8") as f:
        for row in paper_df.to_dict("records"):
            f.write("=" * 80 + "\n")  # 分隔线
            f.write(f"ID: {row.get('ID')}\n")
            f.write(f"FileName: {row.get('FileName')}\n")
            f.write(f"RelativePath: {row.get('RelativePath')}\n")
            f.write(f"Title: {row.get('Title')}\n")
            f.write(f"FullTextChars: {row.get('FullTextChars')}\n")
            f.write(f"NumPages: {row.get('NumPages')}\n")
            f.write(f"ReadError: {row.get('ReadError')}\n")
            f.write("-" * 80 + "\n")
            f.write((row.get("FullText") or "") + "\n")
            f.write("\n")


async def full_text_screening(
        resources_dir: Path,
        output_csv: Path,
        output_txt: Path,
        model: ChatOpenAI,
        *,
        vision_pages: str = "all",
        vision_dpi: int = 180,
        vision_image_format: str = "jpeg",
        vision_jpeg_quality: int = 80,
        batch_size_override: int | None = None,
) -> None:
    """
    全文文献筛选主函数

    Args:
        resources_dir: 资源目录路径
        output_csv: 输出CSV文件路径
        output_txt: 输出文本文件路径
        model: ChatOpenAI模型实例
        vision_pages: 要渲染的PDF页面
        vision_dpi: 图像DPI
        vision_image_format: 图像格式
        vision_jpeg_quality: JPEG质量
        batch_size_override: 覆盖默认批量大小

    Returns:
        None
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for vision-only screening. Install `pymupdf`.")

    # 解析页面规格
    pages_to_use = _parse_page_spec(vision_pages)

    # 加载文献数据
    paper_df = load_fulltext_from_resources(resources_dir)
    if paper_df.empty:
        print(f"No supported files found in: {resources_dir}")
        return

    # 保存全文到文本文件（用于调试）
    write_fulltexts_to_txt(paper_df, output_txt)
    print(f"Saved paper metadata: {output_txt}")

    # 创建AI代理
    agent = create_agent(
        model=model,
        response_format=ToolStrategy(Judge_List),  # 指定输出格式
        system_prompt=systemPromptReason,
    )

    # 处理无法读取的文件
    unreadable_mask = paper_df["ReadError"].astype(str).str.strip().ne("")
    paper_df.loc[unreadable_mask, "Flag"] = "0"
    paper_df.loc[unreadable_mask, "Reason"] = (
            "无法读取全文（读取错误），默认排除。错误信息："
            + paper_df.loc[unreadable_mask, "ReadError"].astype(str)
    )

    # 确定批量大小
    effective_batch_size = batch_size_override or 1

    async def _judge_batch(batch_records: list[dict]) -> list[dict] | None:
        """处理一批文献的筛选"""
        # 纯视觉模式：不发送提取的全文文本，仅发送 PDF 页图像 + 论文元信息
        excluded_results: list[dict] = []
        rendered: list[tuple[dict, list[tuple[int, str]]]] = []

        for record in batch_records:
            if str(record.get("Suffix", "")).lower() != ".pdf":
                excluded_results.append(
                    {
                        "ID": record.get("ID"),
                        "Flag": "0",
                        "Reason": "纯视觉模式仅支持PDF输入，当前文件非PDF，默认排除。",
                    }
                )
                continue

            rel = str(record.get("RelativePath") or "")
            if not rel:
                excluded_results.append(
                    {
                        "ID": record.get("ID"),
                        "Flag": "0",
                        "Reason": "缺少RelativePath，无法定位PDF文件，默认排除。",
                    }
                )
                continue

            pdf_path = PROJECT_DIR / Path(rel)
            try:
                images = _pdf_pages_to_data_urls(
                    pdf_path,
                    pages_to_use,
                    dpi=vision_dpi,
                    image_format=vision_image_format,
                    jpeg_quality=vision_jpeg_quality,
                )
                if not images:
                    raise RuntimeError("No pages rendered")
                rendered.append((record, images))
            except Exception as e:
                excluded_results.append(
                    {
                        "ID": record.get("ID"),
                        "Flag": "0",
                        "Reason": f"无法将PDF渲染为图像，默认排除。错误信息：{e}",
                    }
                )

        if not rendered:
            return excluded_results

        paper_list_for_prompt = [
            {
                "ID": r.get("ID"),
                "Title": r.get("Title"),
                "NumPages": r.get("NumPages"),
                "RelativePath": r.get("RelativePath"),
            }
            for r, _ in rendered
        ]
        prompt_text = userPromptReason.format(paper_list=paper_list_for_prompt)

        content: list[dict] = [{"type": "text", "text": prompt_text}]
        content.append(
            {
                "type": "text",
                "text": (
                    "补充信息：以下为每篇论文的 PDF 页图像（按 Paper ID / Page 标注）。"
                    "请仅依据图像内容完成筛选，不要假设存在未提供的文字全文。"
                ),
            }
        )

        for record, images in rendered:
            for page_number, data_url in images:
                content.append({"type": "text", "text": f"Paper ID {record.get('ID')} - PDF Page {page_number}:"})
                content.append({"type": "image_url", "image_url": {"url": data_url}})

        response = await agent.ainvoke(
            {"messages": [{"role": "user", "content": content}]},
            configurable={"reset_context": True},
        )

        result = response["structured_response"]
        judged_results = [w.model_dump(exclude_none=True) for w in result.judge_list]
        return judged_results + excluded_results

    # 处理可读取的文献
    valid_ids = paper_df.loc[~unreadable_mask, "ID"].tolist()
    for start in range(0, len(valid_ids), effective_batch_size):
        batch_ids = valid_ids[start: start + effective_batch_size]
        # 提取当前批次的文献数据
        batch_df = paper_df.loc[
            paper_df["ID"].isin(batch_ids),
            ["ID", "Title", "RelativePath", "Suffix", "NumPages"],
        ].copy()
        batch_records = batch_df.to_dict("records")

        # 调用AI进行筛选
        judged = await call_with_retry(_judge_batch, batch_records)
        if not judged:
            print(f"Batch {start // effective_batch_size + 1}: failed, leaving empty results")
            continue

        # 更新筛选结果
        for e in judged:
            pid = e.get("ID")
            if pid is None:
                continue
            paper_df.loc[paper_df["ID"] == pid, "Flag"] = str(e.get("Flag", "")).strip()
            paper_df.loc[paper_df["ID"] == pid, "Reason"] = str(e.get("Reason", "")).strip()

        print(f"Batch {start // effective_batch_size + 1} done")
        await asyncio.sleep(1)  # 批处理间延迟，避免API限制

    # 保存结果（不包含全文内容以减小文件大小）
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result_df = paper_df.drop(columns=["FullText"])
    result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"Saved: {output_csv}")


def _build_model(model_name: str, base_url: str) -> ChatOpenAI:
    """
    构建ChatOpenAI模型实例

    Args:
        model_name: 模型名称
        base_url: API基础URL

    Returns:
        ChatOpenAI实例

    Raises:
        RuntimeError: 当API密钥未设置时
    """
    key1 = os.getenv("DMX_API_KEY_1")
    if not key1:
        raise RuntimeError("Missing env var in Screening/.env: DMX_API_KEY_1")
    return ChatOpenAI(model=model_name, base_url=base_url, api_key=key1, temperature=0)  # type: ignore


def _parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Standalone full-text screening (vision-only) from PDFs in ./resources")

    # 输入输出路径参数
    parser.add_argument("--resources-dir", type=Path, default=PROJECT_DIR / "resources",
                        help="资源目录路径")
    parser.add_argument("--output-csv", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_screening_results.csv",
                        help="输出CSV文件路径")
    parser.add_argument("--output-txt", type=Path, default=PROJECT_DIR / "outputs" / "fulltext_sent_to_ai.txt",
                        help="输出文本文件路径")

    # 模型参数
    parser.add_argument("--base-url", type=str, default="https://www.dmxapi.cn/v1",
                        help="API基础URL")
    parser.add_argument("--model", type=str, default="gpt-4.1-mini",
                        help="模型名称")
    parser.add_argument("--batch-size", type=int, default=None,
                        help="覆盖批量大小（默认：1，纯视觉模式建议保持为1）")

    # 视觉模式参数（纯视觉模式固定开启；保留参数用于兼容旧命令）
    parser.add_argument("--vision", action="store_true", default=True,
                        help="(已默认开启) 使用PDF页面图像作为多模态输入（需要PyMuPDF）")
    parser.add_argument("--vision-mode", type=str, default="vision-only",
                        choices=["vision-only", "fallback", "hybrid"],
                        help="(已弃用) 仅支持vision-only；其他值将被忽略")
    parser.add_argument("--vision-pages", type=str, default="all",
                        help="要渲染的页面，如 'all' 或 '1-2,5'")
    parser.add_argument("--vision-dpi", type=int, default=180,
                        help="PDF页面渲染DPI")
    parser.add_argument("--vision-image-format", type=str, default="jpeg",
                        choices=["jpeg", "png", "webp"],
                        help="图像格式")
    parser.add_argument("--vision-jpeg-quality", type=int, default=80,
                        help="JPEG质量（当--vision-image-format=jpeg时）")

    return parser.parse_args()


async def main() -> None:
    """主函数"""
    # 加载环境变量
    load_dotenv(SCRIPT_DIR / ".env", override=True)

    # 解析命令行参数
    args = _parse_args()

    # 构建模型
    model = _build_model(args.model, base_url=args.base_url)

    # 执行全文筛选
    await full_text_screening(
        resources_dir=args.resources_dir,
        output_csv=args.output_csv,
        output_txt=args.output_txt,
        model=model,
        vision_pages=str(args.vision_pages),
        vision_dpi=int(args.vision_dpi),
        vision_image_format=str(args.vision_image_format),
        vision_jpeg_quality=int(args.vision_jpeg_quality),
        batch_size_override=(int(args.batch_size) if args.batch_size else None),
    )


if __name__ == "__main__":
    # 异步运行主函数
    start_time = time.perf_counter()
    try:
        asyncio.run(main())
    finally:
        elapsed_s = time.perf_counter() - start_time
        print(f"Elapsed time: {elapsed_s:.2f}s")
