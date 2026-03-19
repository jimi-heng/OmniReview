from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass(frozen=True)
class Paper:
    """Paper metadata for processing."""

    paper_id: int
    path: Path
    title: str


@dataclass
class ExtractionResult:
    """Result of extraction for a single paper."""

    paper_id: int
    title: str
    relative_path: str
    value_rows: List[Dict[str, str]] = field(default_factory=list)
    evidence_rows: List[Dict[str, str]] = field(default_factory=list)
    error: str = ""

