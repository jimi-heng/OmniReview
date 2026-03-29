# Author: Team 04
# This file is developed by our team

from __future__ import annotations

from dataclasses import dataclass

from flask import current_app

from grpfh.settings import Settings
from grpfh.storage import ProjectPaths


@dataclass(frozen=True, slots=True)
class AppContext:
    settings: Settings
    paths: ProjectPaths


def get_settings() -> Settings:
    settings = current_app.extensions.get("grpfh_settings")
    assert isinstance(settings, Settings)
    return settings


def get_paths() -> ProjectPaths:
    paths = current_app.extensions.get("grpfh_paths")
    assert isinstance(paths, ProjectPaths)
    return paths
