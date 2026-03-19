from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from .http_client import LLMClient
from .models import ExtractionResult, Paper
from .parsing import RobustJSONParser
from .pdf import load_pdf_bytes
from .prompts import (
    generate_columns_section,
    generate_user_prompt,
    get_default_pico,
    get_system_prompt,
)

logger = logging.getLogger(__name__)


class ResponseParser(Protocol):
    def parse(self, text: str, columns: List[str]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]: ...


@dataclass(frozen=True)
class ExtractionRequest:
    llm_columns: List[str]
    pages_spec: Optional[List[int]]
    project_type: str
    pico_dict: Optional[Dict[str, str]]


class EnhancedDataExtractor:
    """Orchestrates PDF->prompt->LLM->parse for a single paper."""

    def __init__(
        self,
        *,
        llm_client: LLMClient,
        parser: ResponseParser = RobustJSONParser,
        project_dir: Path,
        debug_prompt: bool = False,
    ) -> None:
        self._llm = llm_client
        self._parser = parser
        self._project_dir = project_dir
        self._debug_prompt = debug_prompt

    async def extract(self, *, paper: Paper, request: ExtractionRequest) -> ExtractionResult:
        base_error = ""
        value_rows: List[Dict[str, str]] = []
        evidence_rows: List[Dict[str, str]] = []

        pico_dict = request.pico_dict or get_default_pico(request.project_type)

        try:
            pdf_bytes = load_pdf_bytes(paper.path, request.pages_spec)

            columns_section = generate_columns_section(request.llm_columns)
            system_prompt = get_system_prompt(request.project_type)
            user_prompt = generate_user_prompt(
                project_type=request.project_type,
                pico_dict=pico_dict,
                columns_section=columns_section,
                paper_id=paper.paper_id,
            )
            full_prompt = system_prompt + "\n\n" + user_prompt

            if self._debug_prompt:
                logger.debug("Prompt (first 500 chars) for paper_id=%s: %s", paper.paper_id, full_prompt[:500])

            raw_text = await self._llm.extract_text(pdf_bytes=pdf_bytes, filename=paper.path.name, prompt=full_prompt)
            value_rows, evidence_rows = self._parser.parse(raw_text, request.llm_columns)
        except Exception as e:
            base_error = str(e)
            logger.exception("Extraction failed for paper_id=%s", paper.paper_id)
            traceback.print_exc()

        try:
            relative_path = str(paper.path.relative_to(self._project_dir))
        except Exception:
            relative_path = str(paper.path)

        return ExtractionResult(
            paper_id=paper.paper_id,
            title=paper.title,
            relative_path=relative_path,
            value_rows=value_rows,
            evidence_rows=evidence_rows,
            error=base_error,
        )

