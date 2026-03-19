"""Public entrypoints for full-text screening."""

from .full_text_screening.models import (
    FullTextPaper,
    FullTextRequest,
    FullTextScreeningConfig,
    FullTextScreeningRuntime,
)
from .full_text_screening.orchestrator import process_single_paper, run_fulltext, run_fulltext_ai_sync
from .full_text_screening.parsing import extract_conclusion, extract_evidence
from .full_text_screening.pdf import load_pdf_bytes, parse_pages_spec
from .full_text_screening.prompts import (
    PECO_SYSTEM_PROMPT,
    PICOS_SYSTEM_PROMPT,
    PIRO_SYSTEM_PROMPT,
    build_user_prompt,
    get_system_prompt,
    normalize_project_type,
)
from .full_text_screening.runtime import coerce_paper, normalize_pico_dict, resolve_runtime_config

_parse_pages_spec = parse_pages_spec
_load_pdf_bytes = load_pdf_bytes
_normalize_project_type = normalize_project_type
_normalize_pico_dict = normalize_pico_dict
_coerce_paper = coerce_paper
_get_system_prompt = get_system_prompt
_build_user_prompt = build_user_prompt


def _resolve_runtime_config(config):
    return resolve_runtime_config(config, parse_pages_spec=parse_pages_spec)

__all__ = [
    "FullTextPaper",
    "FullTextRequest",
    "FullTextScreeningConfig",
    "FullTextScreeningRuntime",
    "PECO_SYSTEM_PROMPT",
    "PICOS_SYSTEM_PROMPT",
    "PIRO_SYSTEM_PROMPT",
    "extract_conclusion",
    "extract_evidence",
    "load_pdf_bytes",
    "normalize_project_type",
    "parse_pages_spec",
    "process_single_paper",
    "resolve_runtime_config",
    "run_fulltext",
    "run_fulltext_ai_sync",
]
