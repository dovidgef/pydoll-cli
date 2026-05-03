"""Mock-tab tests for upload + batch commands."""

from __future__ import annotations

import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from pydoll_cli.cli import app

runner = CliRunner()


def _stub(tab, browser=None):
    browser = browser or MagicMock()

    @contextlib.asynccontextmanager
    async def _ctx(_opts):
        yield (browser, tab)
    return _ctx


# ---- upload ----------------------------------------------------------------


def test_upload_default_calls_set_input_files(tmp_path: Path):
    f = tmp_path / 'a.png'
    f.write_bytes(b'png')
    element = MagicMock()
    element.set_input_files = AsyncMock()
    element.click = AsyncMock()
    tab = MagicMock()
    tab.query = AsyncMock(return_value=element)
    with patch('pydoll_cli.commands.upload.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'upload', 'input[type=file]', str(f)],
        )
    assert result.exit_code == 0, result.stdout
    element.set_input_files.assert_awaited_once_with([str(f)])
    element.click.assert_not_called()


def test_upload_via_chooser_uses_expect_file_chooser(tmp_path: Path):
    f = tmp_path / 'a.png'
    f.write_bytes(b'png')
    element = MagicMock()
    element.click = AsyncMock()
    element.set_input_files = AsyncMock()
    tab = MagicMock()
    tab.query = AsyncMock(return_value=element)

    chooser_calls: list = []

    @contextlib.asynccontextmanager
    async def fake_chooser(files):
        chooser_calls.append(files)
        yield

    tab.expect_file_chooser = fake_chooser

    with patch('pydoll_cli.commands.upload.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'upload', '.btn', str(f), '--via-chooser'],
        )
    assert result.exit_code == 0, result.stdout
    element.click.assert_awaited_once()
    element.set_input_files.assert_not_called()
    assert chooser_calls == [[str(f)]]


def test_upload_missing_file_exits_2(tmp_path: Path):
    bad = tmp_path / 'does-not-exist.png'
    tab = MagicMock()
    tab.query = AsyncMock(return_value=MagicMock())
    with patch('pydoll_cli.commands.upload.open_browser', _stub(tab)):
        result = runner.invoke(app, ['upload', 'input', str(bad)])
    assert result.exit_code == 2


def test_upload_selector_not_found_exits_4(tmp_path: Path):
    f = tmp_path / 'a.png'
    f.write_bytes(b'')
    tab = MagicMock()
    tab.query = AsyncMock(return_value=None)
    with patch('pydoll_cli.commands.upload.open_browser', _stub(tab)):
        result = runner.invoke(app, ['upload', 'input', str(f)])
    assert result.exit_code == 4


# ---- batch -----------------------------------------------------------------


def test_batch_creates_one_tab_per_url(tmp_path: Path):
    new_tabs: list = []

    class _T:
        def __init__(self, url: str) -> None:
            self.url = url
            self.go_to = AsyncMock()
            self.take_screenshot = AsyncMock()
            self.query = AsyncMock(return_value=None)
            self.close = AsyncMock()

        @property
        def title(self):
            async def _coro() -> str:
                return f'title:{self.url}'
            return _coro()

        @property
        def page_source(self):
            async def _coro() -> str:
                return f'<html>{self.url}</html>'
            return _coro()

    async def fake_new_tab(url='', browser_context_id=None):
        t = _T(url)
        new_tabs.append((url, t))
        return t

    browser = MagicMock()
    browser.new_tab = AsyncMock(side_effect=fake_new_tab)
    tab = MagicMock()

    with patch('pydoll_cli.commands.batch.open_browser', _stub(tab, browser=browser)):
        result = runner.invoke(
            app,
            [
                '--output', 'json', 'batch',
                'https://a.com', 'https://b.com',
                '--screenshot-dir', str(tmp_path / 'shots'),
            ],
        )
    assert result.exit_code == 0, result.stdout
    assert browser.new_tab.await_count == 2
    assert {u for u, _ in new_tabs} == {'https://a.com', 'https://b.com'}
    # Screenshots written to the dir.
    assert (tmp_path / 'shots').exists()
