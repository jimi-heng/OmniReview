# Author: Team 04
# This file is developed by our team

"""
Enhanced Data Extraction (CLI facade).

Implementation lives in `Screening/data_extraction/`. This file remains a stable
entrypoint for:
- `grpfh/app.py` subprocess calls
- `Screening/evals/data_extraction/data_extraction_eval.py`
"""

from __future__ import annotations

from data_extraction.cli import main


if __name__ == "__main__":
    main()

