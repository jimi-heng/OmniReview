from __future__ import annotations

from pathlib import Path

from grpfh.storage import ProjectPaths, is_within_directory, safe_storage_name


def test_is_within_directory_valid(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    cand = base / "a" / "b.txt"
    cand.parent.mkdir(parents=True)
    cand.write_text("x", encoding="utf-8")
    assert is_within_directory(cand, base) is True


def test_is_within_directory_traversal(tmp_path: Path):
    base = tmp_path / "base"
    base.mkdir()
    cand = base / ".." / "etc" / "passwd"
    assert is_within_directory(cand, base) is False


def test_project_paths_pdf_dir(tmp_path: Path):
    paths = ProjectPaths(resources_root=tmp_path / "res", outputs_root=tmp_path / "out")
    assert str(paths.project_pdf_dir(7, 9)).endswith(r"res\users\user_7\projects\project_9\pdf")


def test_project_paths_output(tmp_path: Path):
    paths = ProjectPaths(resources_root=tmp_path / "res", outputs_root=tmp_path / "out")
    csv_path, xlsx_path = paths.project_output_paths(1, 2)
    assert str(csv_path).endswith(r"out\users\user_1\projects\project_2\proj_2_extracted.csv")
    assert str(xlsx_path).endswith(r"out\users\user_1\projects\project_2\proj_2_extracted.xlsx")


def test_safe_storage_name_fallback():
    assert safe_storage_name("", "fallback") == "fallback"
    assert safe_storage_name(None, "fallback") == "fallback"

