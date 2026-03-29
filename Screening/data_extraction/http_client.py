# Author: Team 04
# This file is developed by our team

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any, Dict, Protocol

import httpx


class LLMClient(Protocol):
    async def extract_text(self, *, pdf_bytes: bytes, filename: str, prompt: str) -> str: ...


async def post_with_auth_fallback(
    client: httpx.AsyncClient,
    url: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout_s: float,
) -> httpx.Response:
    headers1 = {"Authorization": api_key, "Content-Type": "application/json"}
    r1 = await client.post(url, headers=headers1, json=payload, timeout=timeout_s)
    if r1.status_code not in (401, 403):
        return r1

    headers2 = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return await client.post(url, headers=headers2, json=payload, timeout=timeout_s)


async def call_with_retry(coro_func, *args, retries: int, delay_s: float):
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            return await coro_func(*args)
        except Exception as exc:
            last_exc = exc
            await asyncio.sleep(delay_s)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Retry failed")


def extract_output_text(resp_json: Dict[str, Any]) -> str:
    out_parts: list[str] = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        for block in item.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    out_parts.append(text)

    if out_parts:
        return "\n".join(out_parts)

    for key in ("output_text", "text"):
        value = resp_json.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


@dataclass(frozen=True)
class ResponsesAPIConfig:
    endpoint: str
    api_key: str
    model: str
    timeout_s: float
    retries: int
    retry_delay_s: float


class ResponsesAPIClient:
    """Minimal client for OpenAI-compatible /responses endpoints (file + prompt)."""

    def __init__(self, *, http_client: httpx.AsyncClient, config: ResponsesAPIConfig):
        self._http = http_client
        self._cfg = config

    async def extract_text(self, *, pdf_bytes: bytes, filename: str, prompt: str) -> str:
        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        payload = {
            "model": self._cfg.model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_file",
                            "filename": filename,
                            "file_data": f"data:application/pdf;base64,{b64}",
                        },
                        {"type": "input_text", "text": prompt},
                    ],
                }
            ],
        }

        resp: httpx.Response = await call_with_retry(
            post_with_auth_fallback,
            self._http,
            self._cfg.endpoint,
            self._cfg.api_key,
            payload,
            self._cfg.timeout_s,
            retries=self._cfg.retries,
            delay_s=self._cfg.retry_delay_s,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        return extract_output_text(resp.json())

