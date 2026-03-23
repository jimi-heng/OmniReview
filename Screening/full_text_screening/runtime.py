import asyncio
import base64
import json
import mimetypes
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import httpx
from dotenv import load_dotenv

from .models import FullTextPaper, FullTextScreeningConfig, FullTextScreeningRuntime
from .pico_normalizer import coerce_pico_payload, flatten_text


SCRIPT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(SCRIPT_DIR / ".env", override=True)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"0", "false", "no", "n", "off"}:
        return False
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    return default


def normalize_pico_dict(pico_dict: Mapping[str, Any] | list[Any] | None) -> dict[str, str]:
    return {
        str(key).strip().lower(): flatten_text(value)
        for key, value in coerce_pico_payload(pico_dict).items()
    }


def coerce_paper(paper: Any) -> FullTextPaper:
    if isinstance(paper, FullTextPaper):
        return paper
    if not isinstance(paper, Mapping):
        raise TypeError(f"Unsupported paper input: {type(paper)!r}")

    paper_id = int(paper["id"])
    source_value = paper.get("pdf_path") or paper.get("source_path") or paper.get("file_path") or paper.get("path")
    if not source_value:
        raise KeyError("Paper mapping must include `pdf_path`, `source_path`, `file_path`, or `path`.")
    pdf_path = Path(str(source_value))
    title = str(paper.get("title") or pdf_path.stem)
    return FullTextPaper(paper_id=paper_id, title=title, pdf_path=pdf_path)


def _build_file_block(file_bytes: bytes, filename: str) -> dict[str, str]:
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    b64 = base64.b64encode(file_bytes).decode("ascii")
    return {"type": "input_file", "filename": filename, "file_data": f"data:{mime_type};base64,{b64}"}


def build_payload(
    model_name: str,
    *,
    prompt: str,
    filename: str | None = None,
    file_bytes: bytes | None = None,
    document_text: str | None = None,
) -> dict[str, Any]:
    content: list[dict[str, str]] = []
    if file_bytes is not None:
        if not filename:
            raise ValueError("`filename` is required when `file_bytes` is provided.")
        content.append(_build_file_block(file_bytes, filename))
    elif document_text is not None:
        label = filename or "document.txt"
        content.append({"type": "input_text", "text": f"Full-text content from {label}:\n\n{document_text}"})
    else:
        raise ValueError("Either `file_bytes` or `document_text` must be provided.")

    content.append({"type": "input_text", "text": prompt})
    return {
        "model": model_name,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }


def error_result(
    paper_id: int,
    *,
    error_type: str = "runtime_error",
    message: str = "",
    raw_output: str = "",
) -> dict[str, Any]:
    evidence = {
        "error_type": error_type,
        "message": message,
    }
    if raw_output:
        evidence["raw_output"] = raw_output
    return {"id": paper_id, "decision": "Error", "evidence": json.dumps(evidence, ensure_ascii=False), "hl_path": None}


def read_env_config() -> FullTextScreeningConfig:
    return FullTextScreeningConfig(
        base_url=os.getenv("WEB_FULLTEXT_BASE_URL", "https://www.dmxapi.cn/v1"),
        model=os.getenv("WEB_FULLTEXT_MODEL", "gpt-4.1"),
        api_key_env=os.getenv("WEB_FULLTEXT_API_KEY_ENV", "DMX_API_KEY_1"),
        timeout=float(os.getenv("WEB_FULLTEXT_TIMEOUT", "300.0")),
        retries=int(os.getenv("WEB_FULLTEXT_RETRIES", "3")),
        retry_delay=float(os.getenv("WEB_FULLTEXT_RETRY_DELAY", "3.0")),
        max_concurrency=int(os.getenv("WEB_FULLTEXT_MAX_CONCURRENCY", "5")),
        pdf_pages=os.getenv("WEB_FULLTEXT_PDF_PAGES", "all"),
        enable_highlight=_coerce_bool(os.getenv("WEB_FULLTEXT_ENABLE_HIGHLIGHT", "1"), default=True),
    )


def resolve_runtime_config(
    config: FullTextScreeningConfig | Mapping[str, Any] | None,
    *,
    parse_pages_spec,
) -> FullTextScreeningRuntime:
    default_cfg = read_env_config()
    endpoint_override: str | None = None

    if config is None:
        merged = asdict(default_cfg)
    elif isinstance(config, FullTextScreeningConfig):
        merged = asdict(config)
    elif isinstance(config, Mapping):
        merged = {**asdict(default_cfg), **dict(config)}
        endpoint_value = merged.pop("endpoint", None)
        if endpoint_value:
            endpoint_override = str(endpoint_value)
    else:
        raise TypeError(f"Unsupported config input: {type(config)!r}")

    resolved = FullTextScreeningConfig(**merged)
    api_key = os.getenv(resolved.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing env var in Screening/.env: {resolved.api_key_env}")

    endpoint = endpoint_override or resolved.base_url.rstrip("/") + "/responses"
    pdf_pages = str(resolved.pdf_pages or "all")
    return FullTextScreeningRuntime(
        endpoint=endpoint,
        api_key=api_key,
        model=resolved.model,
        timeout=max(1.0, float(resolved.timeout)),
        retries=max(1, int(resolved.retries)),
        retry_delay=max(0.0, float(resolved.retry_delay)),
        max_concurrency=max(1, int(resolved.max_concurrency)),
        pdf_pages=pdf_pages,
        selected_pages=parse_pages_spec(pdf_pages),
        enable_highlight=_coerce_bool(resolved.enable_highlight, default=True),
    )


async def call_with_retry(coro_func, *args, retries=3, delay_s=3.0):
    last_exc = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(delay_s)
    raise last_exc


async def post_with_auth_fallback(client, url, api_key, payload, timeout_s):
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    response = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if response.status_code not in (401, 403):
        return response

    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)
