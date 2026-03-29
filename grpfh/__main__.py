# Author: Team 04
# This file is developed by our team

from __future__ import annotations

# `python -m grpfh` is the intended entrypoint.
# Some runners (and some accidental invocations) may execute this file directly
# (e.g. `python grpfh/__main__.py`), which would set sys.path to `.../grpfh` and
# break `import grpfh.*`. Make it robust either way.
import sys
from pathlib import Path

try:
    from .app import main  # type: ignore
except Exception:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    from grpfh.app import main


if __name__ == "__main__":
    main()
