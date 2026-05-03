"""Verify --human flags reach pydoll's element APIs as humanize=True.

Regression for the silent-failure mode where `click --human` and `type --human`
exited 0 but issued raw CDP calls (no humanization). Fixed in 0.1.6.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from typer.testing import CliRunner

from pydoll_cli.cli import app

runner = CliRunner()


def _stub_browser(tab: MagicMock) -> contextlib.AbstractAsyncContextManager:
    @contextlib.asynccontextmanager
    async def _ctx(opts):
        yield (MagicMock(), tab)

    return _ctx


class _Tab:
    """Hand-rolled tab stub: pydoll's `current_url` is an awaitable property."""

    def __init__(self, element: MagicMock) -> None:
        self.go_to = AsyncMock()
        self.query = AsyncMock(return_value=element)

    @property
    def current_url(self):  # type: ignore[no-untyped-def]
        async def _coro() -> str:
            return ''
        return _coro()


def _make_tab(element: MagicMock) -> _Tab:
    return _Tab(element)


def test_click_human_passes_humanize_true():
    element = MagicMock()
    element.click = AsyncMock()
    element.click_using_js = AsyncMock()
    tab = _make_tab(element)

    with patch('pydoll_cli.commands.click.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'click', 'https://example.com', 'a.x', '--human'],
        )

    assert result.exit_code == 0, result.stdout
    element.click.assert_awaited_once_with(humanize=True)
    element.click_using_js.assert_not_called()


def test_click_fast_uses_click_using_js():
    element = MagicMock()
    element.click = AsyncMock()
    element.click_using_js = AsyncMock()
    tab = _make_tab(element)

    with patch('pydoll_cli.commands.click.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'click', 'https://example.com', 'a.x', '--fast'],
        )

    assert result.exit_code == 0, result.stdout
    element.click_using_js.assert_awaited_once_with()
    element.click.assert_not_called()


def test_type_human_passes_humanize_true():
    element = MagicMock()
    element.type_text = AsyncMock()
    element.insert_text = AsyncMock()
    tab = _make_tab(element)

    with patch('pydoll_cli.commands.type_.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            [
                '--output', 'json', 'type',
                'https://example.com', 'input[name=q]', 'pydoll', '--human',
            ],
        )

    assert result.exit_code == 0, result.stdout
    element.type_text.assert_awaited_once_with('pydoll', humanize=True)
    element.insert_text.assert_not_called()


def test_type_default_uses_insert_text():
    element = MagicMock()
    element.type_text = AsyncMock()
    element.insert_text = AsyncMock()
    tab = _make_tab(element)

    with patch('pydoll_cli.commands.type_.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'type',
             'https://example.com', 'input[name=q]', 'pydoll'],
        )

    assert result.exit_code == 0, result.stdout
    element.insert_text.assert_awaited_once_with('pydoll')
    element.type_text.assert_not_called()


def test_type_explicit_delay_ms_uses_constant_interval():
    element = MagicMock()
    element.type_text = AsyncMock()
    element.insert_text = AsyncMock()
    tab = _make_tab(element)

    with patch('pydoll_cli.commands.type_.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            [
                '--output', 'json', 'type',
                'https://example.com', 'input[name=q]', 'pydoll',
                '--delay-ms', '120',
            ],
        )

    assert result.exit_code == 0, result.stdout
    element.type_text.assert_awaited_once_with('pydoll', interval=0.12)
    element.insert_text.assert_not_called()
