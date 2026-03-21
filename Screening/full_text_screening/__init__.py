from .cli import async_main, build_arg_parser, main
from .models import (
    FullTextPaper,
    NormalizedPICO,
    FullTextRequest,
    FullTextScreeningConfig,
    FullTextScreeningRuntime,
)
from .orchestrator import process_single_paper, run_fulltext, run_fulltext_ai_sync
from .parsing import extract_conclusion, extract_evidence
from .pdf import discover_pdfs, load_pdf_bytes, parse_pages_spec
from .pico_normalizer import coerce_pico_payload, normalize_pico_input
from .prompts import (
    PECO_SYSTEM_PROMPT,
    PICOS_SYSTEM_PROMPT,
    PIRO_SYSTEM_PROMPT,
    normalize_project_type,
)
from .runtime import resolve_runtime_config

__all__ = [
    "FullTextPaper",
    "NormalizedPICO",
    "FullTextRequest",
    "FullTextScreeningConfig",
    "FullTextScreeningRuntime",
    "PECO_SYSTEM_PROMPT",
    "PICOS_SYSTEM_PROMPT",
    "PIRO_SYSTEM_PROMPT",
    "async_main",
    "build_arg_parser",
    "coerce_pico_payload",
    "discover_pdfs",
    "extract_conclusion",
    "extract_evidence",
    "load_pdf_bytes",
    "main",
    "normalize_pico_input",
    "normalize_project_type",
    "parse_pages_spec",
    "process_single_paper",
    "resolve_runtime_config",
    "run_fulltext",
    "run_fulltext_ai_sync",
]
