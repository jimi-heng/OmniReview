from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class FullTextPaper:
    paper_id: int
    title: str
    pdf_path: Path


@dataclass(frozen=True)
class FullTextRequest:
    paper: FullTextPaper
    pico_dict: dict[str, str]
    project_type: str


@dataclass(frozen=True)
class FullTextScreeningConfig:
    base_url: str = "https://www.dmxapi.cn/v1"
    model: str = "gpt-4.1"
    api_key_env: str = "DMX_API_KEY_1"
    timeout: float = 300.0
    retries: int = 3
    retry_delay: float = 3.0
    max_concurrency: int = 5
    pdf_pages: str = "all"
    enable_highlight: bool = True


@dataclass(frozen=True)
class FullTextScreeningRuntime:
    endpoint: str
    api_key: str
    model: str
    timeout: float
    retries: int
    retry_delay: float
    max_concurrency: int
    pdf_pages: str
    selected_pages: Optional[list[int]]
    enable_highlight: bool
