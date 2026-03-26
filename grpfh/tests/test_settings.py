from __future__ import annotations

import os

from grpfh.settings import load_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("GRPFH_HOST", raising=False)
    monkeypatch.delenv("GRPFH_PORT", raising=False)
    monkeypatch.delenv("GRPFH_DEBUG", raising=False)
    s = load_settings()
    assert s.host == "127.0.0.1"
    assert s.port == 3000
    assert s.debug is True


def test_env_override(monkeypatch):
    monkeypatch.setenv("GRPFH_HOST", "0.0.0.0")
    monkeypatch.setenv("GRPFH_PORT", "9999")
    monkeypatch.setenv("GRPFH_DEBUG", "false")
    s = load_settings()
    assert s.host == "0.0.0.0"
    assert s.port == 9999
    assert s.debug is False


def test_debug_falsy(monkeypatch):
    for v in ["0", "false", "no", "off"]:
        monkeypatch.setenv("GRPFH_DEBUG", v)
        assert load_settings().debug is False


def test_max_upload_mb(monkeypatch):
    monkeypatch.setenv("GRPFH_MAX_UPLOAD_MB", "50")
    s = load_settings()
    assert s.max_content_length_bytes == 50 * 1024 * 1024


def test_max_upload_mb_non_digit(monkeypatch):
    monkeypatch.setenv("GRPFH_MAX_UPLOAD_MB", "abc")
    s = load_settings()
    assert s.max_content_length_bytes is None

