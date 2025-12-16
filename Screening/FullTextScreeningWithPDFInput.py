import argparse
import asyncio
import base64
import os
import re
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing import Literal, List, Optional

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None

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


def _extract_pdf_text(pdf_path: Path) -> tuple[str, str, int]:
    try:
        from pypdf import PdfReader  # local import: avoid hard dependency when not needed
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"pypdf is required for PDF text extraction: {e}") from e

    reader = PdfReader(str(pdf_path))
    meta_title = ""
    try:
        if reader.metadata and reader.metadata.title:
            meta_title = str(reader.metadata.title).strip()
    except Exception:
        meta_title = ""

    try:
        num_pages = len(reader.pages)
    except Exception:
        num_pages = 0

    parts: list[str] = []
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text.strip():
            parts.append(page_text)
    return ("\n\n".join(parts), meta_title, num_pages)


def _extract_pdf_metadata_with_pymupdf(pdf_path: Path) -> tuple[str, int]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for PDF metadata in vision-only mode. Install `pymupdf`.")
    with fitz.open(str(pdf_path)) as doc:
        meta_title = ""
        try:
            meta_title = str((doc.metadata or {}).get("title") or "").strip()
        except Exception:
            meta_title = ""
        return meta_title, int(doc.page_count)


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _parse_page_spec(spec: str) -> list[int] | None:
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
            start_s, end_s = part.split("-", 1)
            start = int(start_s.strip())
            end = int(end_s.strip())
            if start <= 0 or end <= 0:
                continue
            if start > end:
                start, end = end, start
            pages.update(range(start, end + 1))
        else:
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
    if fitz is None:
        raise RuntimeError("PyMuPDF is required for vision PDF input. Install `pymupdf`.")

    fmt = (image_format or "").lower().strip()
    if fmt not in {"png", "jpeg", "webp"}:
        raise ValueError(f"Unsupported image format: {image_format}")

    with fitz.open(str(pdf_path)) as doc:
        page_count = doc.page_count
        if pages is None:
            selected = list(range(1, page_count + 1))
        else:
            selected = [p for p in pages if 1 <= p <= page_count]

        out: list[tuple[int, str]] = []
        for page_number in selected:
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(dpi=dpi, alpha=False)

            if fmt == "png":
                img_bytes = pix.tobytes("png")
                mime = "image/png"
            elif fmt == "webp":
                img_bytes = pix.tobytes(output="webp")
                mime = "image/webp"
            else:
                img_bytes = pix.tobytes(output="jpeg", jpg_quality=int(jpeg_quality))
                mime = "image/jpeg"

            b64 = base64.b64encode(img_bytes).decode("ascii")
            out.append((page_number, f"data:{mime};base64,{b64}"))
        return out


def load_fulltext_from_resources(resources_dir: Path, *, extract_pdf_text: bool = True) -> pd.DataFrame:
    resources_dir = resources_dir.resolve()
    if not resources_dir.exists():
        raise FileNotFoundError(f"resources folder not found: {resources_dir}")

    supported_exts = {".pdf", ".txt", ".md"}
    files = sorted(
        [p for p in resources_dir.rglob("*") if p.is_file() and p.suffix.lower() in supported_exts],
        key=lambda p: str(p).lower(),
    )

    rows: list[dict] = []
    for idx, path in enumerate(files):
        path = path.resolve()
        title = path.stem
        full_text = ""
        num_pages = 0
        error = ""

        try:
            if path.suffix.lower() == ".pdf":
                if extract_pdf_text:
                    full_text, meta_title, num_pages = _extract_pdf_text(path)
                    if meta_title:
                        title = meta_title
                else:
                    meta_title, num_pages = _extract_pdf_metadata_with_pymupdf(path)
                    if meta_title:
                        title = meta_title
                    full_text = ""
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
                "RelativePath": str(path.relative_to(PROJECT_DIR)) if PROJECT_DIR in path.parents else str(path),
                "Suffix": path.suffix.lower(),
                "Title": title,
                "FullTextPreview": preview,
                "FullTextChars": len(normalized),
                "NumPages": num_pages,
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
    vision: bool = False,
    vision_mode: str = "fallback",
    vision_pages: str = "all",
    vision_if_text_lt: int = 200,
    vision_always_for_pdf: bool = True,
    vision_dpi: int = 180,
    vision_image_format: str = "jpeg",
    vision_jpeg_quality: int = 80,
    batch_size_override: int | None = None,
) -> None:
    pages_to_use = _parse_page_spec(vision_pages)
    extract_pdf_text = not (vision and pages_to_use is None)
    if vision and pages_to_use is None:
        print("Vision enabled with all pages -> skipping PDF text extraction (not using pypdf).")

    paper_df = load_fulltext_from_resources(resources_dir, extract_pdf_text=extract_pdf_text)
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

    effective_batch_size = batch_size_override or (1 if vision else batch_size)

    def _needs_vision(record: dict) -> bool:
        if not vision:
            return False
        if str(record.get("Suffix", "")).lower() != ".pdf":
            return False
        if vision_always_for_pdf:
            return True
        try:
            return int(record.get("FullTextChars") or 0) < int(vision_if_text_lt)
        except Exception:
            return True

    async def _judge_batch(batch_records: list[dict]) -> list[dict] | None:
        prompt_text = userPromptReason.format(paper_list=batch_records)

        use_vision_in_call = any(_needs_vision(r) for r in batch_records) and vision_mode != "text-only"
        if use_vision_in_call:
            content: list[dict] = [{"type": "text", "text": prompt_text}]
            content.append(
                {
                    "type": "text",
                    "text": (
                        "补充信息：部分论文提供了 PDF 页面的图片（按 Paper ID / Page 标注）。"
                        "请结合文字全文与图片内容共同判断。"
                    ),
                }
            )

            for r in batch_records:
                if not _needs_vision(r):
                    continue
                rel = str(r.get("RelativePath") or "")
                if not rel:
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
                except Exception as e:
                    print(f"Vision rendering failed for {pdf_path}: {e}")
                    continue

                for page_number, data_url in images:
                    content.append({"type": "text", "text": f"Paper ID {r.get('ID')} - PDF Page {page_number}:"})
                    content.append({"type": "image_url", "image_url": {"url": data_url}})

            try:
                response = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": content}]},
                    configurable={"reset_context": True},
                )
            except Exception as e:
                if vision_mode == "fallback":
                    print(f"Vision call failed, falling back to text-only: {e}")
                    response = await agent.ainvoke(
                        {"messages": [{"role": "user", "content": prompt_text}]},
                        configurable={"reset_context": True},
                    )
                else:
                    raise
        else:
            response = await agent.ainvoke(
                {"messages": [{"role": "user", "content": prompt_text}]},
                configurable={"reset_context": True},
            )

        result = response["structured_response"]
        return [w.model_dump(exclude_none=True) for w in result.judge_list]

    valid_ids = paper_df.loc[~unreadable_mask, "ID"].tolist()
    for start in range(0, len(valid_ids), effective_batch_size):
        batch_ids = valid_ids[start : start + effective_batch_size]
        batch_df = paper_df.loc[
            paper_df["ID"].isin(batch_ids),
            ["ID", "Title", "RelativePath", "Suffix", "FullTextChars", "FullText"],
        ].copy()
        batch_records = batch_df.to_dict("records")

        judged = await call_with_retry(_judge_batch, batch_records)
        if not judged:
            print(f"Batch {start // effective_batch_size + 1}: failed, leaving empty results")
            continue

        for e in judged:
            pid = e.get("ID")
            if pid is None:
                continue
            paper_df.loc[paper_df["ID"] == pid, "Flag"] = str(e.get("Flag", "")).strip()
            paper_df.loc[paper_df["ID"] == pid, "Reason"] = str(e.get("Reason", "")).strip()

        print(f"Batch {start // effective_batch_size + 1} done")
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
    parser.add_argument("--batch-size", type=int, default=None, help="Override batch size (default: 6, or 1 when --vision)")

    parser.add_argument("--vision", action="store_true", help="Enable PDF page images as multimodal input (PyMuPDF required).")
    parser.add_argument(
        "--vision-mode",
        type=str,
        default="fallback",
        choices=["fallback", "hybrid", "text-only"],
        help="fallback: try vision then text-only; hybrid: require vision; text-only: ignore vision.",
    )
    parser.add_argument("--vision-pages", type=str, default="all", help="Pages to render, e.g. 'all' or '1-2,5'")
    parser.add_argument("--vision-if-text-lt", type=int, default=200, help="Use vision when extracted text chars < N")
    parser.add_argument("--vision-always-for-pdf", action="store_true", default=True, help="Always attach PDF page images for PDFs")
    parser.add_argument("--vision-dpi", type=int, default=180, help="Render DPI for PDF pages")
    parser.add_argument("--vision-image-format", type=str, default="jpeg", choices=["jpeg", "png", "webp"])
    parser.add_argument("--vision-jpeg-quality", type=int, default=80, help="JPEG quality when --vision-image-format=jpeg")
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
        vision=bool(args.vision),
        vision_mode=str(args.vision_mode),
        vision_pages=str(args.vision_pages),
        vision_if_text_lt=int(args.vision_if_text_lt),
        vision_always_for_pdf=bool(args.vision_always_for_pdf),
        vision_dpi=int(args.vision_dpi),
        vision_image_format=str(args.vision_image_format),
        vision_jpeg_quality=int(args.vision_jpeg_quality),
        batch_size_override=(int(args.batch_size) if args.batch_size else None),
    )


if __name__ == "__main__":
    asyncio.run(main())
