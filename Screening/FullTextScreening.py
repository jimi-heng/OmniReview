# Author: Team 04
# This file is developed by our team

"""
Full Text Screening (stable entrypoint).

Implementation lives in `Screening/full_text_screening/`. This file remains the
stable entrypoint for:
- `grpfh/app.py` imports
- direct CLI execution
"""

from __future__ import annotations

try:
    from .full_text_screening import (
        FullTextPaper,
        NormalizedPICO,
        FullTextRequest,
        FullTextScreeningConfig,
        FullTextScreeningRuntime,
        PECO_SYSTEM_PROMPT,
        PICOS_SYSTEM_PROMPT,
        PIRO_SYSTEM_PROMPT,
        build_arg_parser,
        coerce_pico_payload,
        discover_pdfs,
        extract_conclusion,
        extract_evidence,
        load_pdf_bytes,
        main,
        normalize_pico_input,
        normalize_project_type,
        parse_pages_spec,
        process_single_paper,
        resolve_runtime_config,
        run_fulltext,
        run_fulltext_ai_sync,
    )
except ImportError:
    from full_text_screening import (
        FullTextPaper,
        NormalizedPICO,
        FullTextRequest,
        FullTextScreeningConfig,
        FullTextScreeningRuntime,
        PECO_SYSTEM_PROMPT,
        PICOS_SYSTEM_PROMPT,
        PIRO_SYSTEM_PROMPT,
        build_arg_parser,
        coerce_pico_payload,
        discover_pdfs,
        extract_conclusion,
        extract_evidence,
        load_pdf_bytes,
        main,
        normalize_pico_input,
        normalize_project_type,
        parse_pages_spec,
        process_single_paper,
        resolve_runtime_config,
        run_fulltext,
        run_fulltext_ai_sync,
    )

__all__ = [
    "FullTextPaper",
    "NormalizedPICO",
    "FullTextRequest",
    "FullTextScreeningConfig",
    "FullTextScreeningRuntime",
    "PECO_SYSTEM_PROMPT",
    "PICOS_SYSTEM_PROMPT",
    "PIRO_SYSTEM_PROMPT",
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


if __name__ == "__main__":
    main()
