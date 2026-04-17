"""Unit tests for browser detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from pydoll_cli import browsers


def test_detect_all_returns_list(monkeypatch):
    monkeypatch.setattr(browsers, 'find', lambda kind: Path(f'/fake/{kind}'))
    got = browsers.detect_all()
    kinds = {c.kind for c in got}
    assert {'chrome', 'edge', 'wavebox', 'chromium'} == kinds


def test_find_returns_none_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(browsers.shutil, 'which', lambda _cmd: None)
    monkeypatch.setattr(browsers.Path, 'is_file', lambda self: False)
    assert browsers.find('chrome') is None


def test_require_raises_with_helpful_message(monkeypatch):
    monkeypatch.setattr(browsers.shutil, 'which', lambda _cmd: None)
    monkeypatch.setattr(browsers.Path, 'is_file', lambda self: False)
    with pytest.raises(FileNotFoundError, match='--browser-binary'):
        browsers.require('wavebox')
