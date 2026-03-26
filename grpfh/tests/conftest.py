from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.security import generate_password_hash

from grpfh.app import create_app
from grpfh.database import connect
from grpfh.settings import Settings


@dataclass(frozen=True, slots=True)
class Seed:
    user_id: int
    legacy_user_id: int
    other_user_id: int
    project_id: int
    other_project_id: int
    literature_ids: list[int]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        host="127.0.0.1",
        port=3000,
        debug=True,
        db_path=tmp_path / "test.db",
        resources_root=tmp_path / "resources",
        outputs_root=tmp_path / "outputs",
        cors_origins="*",
        max_content_length_bytes=None,
    )


@pytest.fixture(autouse=True)
def mock_screening_modules() -> Any:
    """Block all Screening imports and provide controllable mocks.

    The Flask routes perform delayed imports like:
    - from Screening.AbstractScreening import run_ai_screening_sync, literature_search_all
    - from Screening.FullTextScreening import run_fulltext_ai_sync
    - from Screening.paper_download import ImprovedPaperDownloader
    """

    screening_root = MagicMock(name="Screening")
    abstract_mod = MagicMock(name="Screening.AbstractScreening")
    fulltext_mod = MagicMock(name="Screening.FullTextScreening")
    paper_download_mod = MagicMock(name="Screening.paper_download")

    # Reasonable defaults (tests can override per-test).
    abstract_mod.literature_search_all.return_value = []
    abstract_mod.run_ai_screening_sync.return_value = []
    fulltext_mod.run_fulltext_ai_sync.return_value = []

    # Downloader class default: always fail downloads unless overridden.
    downloader_instance = MagicMock(name="ImprovedPaperDownloader()")
    downloader_instance.download_paper.return_value = False
    paper_download_mod.ImprovedPaperDownloader.return_value = downloader_instance

    screening_root.AbstractScreening = abstract_mod
    screening_root.FullTextScreening = fulltext_mod
    screening_root.paper_download = paper_download_mod

    with patch.dict(
        sys.modules,
        {
            "Screening": screening_root,
            "Screening.AbstractScreening": abstract_mod,
            "Screening.FullTextScreening": fulltext_mod,
            "Screening.paper_download": paper_download_mod,
        },
    ):
        yield SimpleNamespace(
            Screening=screening_root,
            AbstractScreening=abstract_mod,
            FullTextScreening=fulltext_mod,
            paper_download=paper_download_mod,
            downloader_instance=downloader_instance,
        )


@pytest.fixture
def app(settings: Settings):
    app = create_app(settings)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seeded_db(settings: Settings) -> Seed:
    """Seed a minimal dataset used by API integration tests."""

    with connect(settings.db_path) as conn:
        cur = conn.cursor()

        # Users
        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            ("user@example.com", generate_password_hash("password123")),
        )
        user_id = int(cur.lastrowid)

        legacy_md5 = hashlib.md5("legacy123".encode()).hexdigest()
        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            ("legacy@example.com", legacy_md5),
        )
        legacy_user_id = int(cur.lastrowid)

        cur.execute(
            "INSERT INTO users (email, password) VALUES (?, ?)",
            ("other@example.com", generate_password_hash("password123")),
        )
        other_user_id = int(cur.lastrowid)

        # Projects
        cur.execute(
            "INSERT INTO projects (user_id, project_name, status) VALUES (?, ?, ?)",
            (user_id, "Test Project", "PICO Setup"),
        )
        project_id = int(cur.lastrowid)

        cur.execute(
            "INSERT INTO projects (user_id, project_name, status) VALUES (?, ?, ?)",
            (other_user_id, "Other Project", "PICO Setup"),
        )
        other_project_id = int(cur.lastrowid)

        # Project data (pico/protocol/project_type)
        cur.execute(
            "INSERT INTO project_data (project_id, data_type, data_content) VALUES (?, ?, ?)",
            (project_id, "project_type", '"SPICO"'),
        )
        cur.execute(
            "INSERT INTO project_data (project_id, data_type, data_content) VALUES (?, ?, ?)",
            (project_id, "pico", '{"p":"P","i":"I","c":"C","o":"O","s":"S"}'),
        )
        cur.execute(
            "INSERT INTO project_data (project_id, data_type, data_content) VALUES (?, ?, ?)",
            (project_id, "protocol", '{"criteria":"Criteria"}'),
        )

        # Literatures (various decisions)
        literature_ids: list[int] = []
        for title, ai_decision, user_decision, pdf_status in [
            ("Pending Paper", "Pending", "Keep", "Pending"),
            ("Included Paper", "Included", "Keep", "Downloaded"),
            ("Excluded Paper", "Excluded", "Keep", "Pending"),
            ("Error Paper", "Error", "Keep", "Pending"),
        ]:
            cur.execute(
                """
                INSERT INTO literatures
                (project_id, title, author, journal, year, doi, abstract, ai_decision, user_decision, reasoning, pdf_status)
                VALUES (?, ?, '', '', 2024, '10.1234/test', 'abs', ?, ?, 'reason', ?)
                """,
                (project_id, title, ai_decision, user_decision, pdf_status),
            )
            literature_ids.append(int(cur.lastrowid))

        conn.commit()

    return Seed(
        user_id=user_id,
        legacy_user_id=legacy_user_id,
        other_user_id=other_user_id,
        project_id=project_id,
        other_project_id=other_project_id,
        literature_ids=literature_ids,
    )

