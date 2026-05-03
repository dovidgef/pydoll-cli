"""Mock-tab tests for keyboard / mouse / scroll wiring + arg validation."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

from pydoll.constants import Key, ScrollPosition
from pydoll.protocol.input.types import KeyModifier, MouseButton
from typer.testing import CliRunner

from pydoll_cli.cli import app

runner = CliRunner()


def _stub(tab):
    @contextlib.asynccontextmanager
    async def _ctx(_opts):
        yield (MagicMock(), tab)
    return _ctx


# ---- keyboard --------------------------------------------------------------


def test_keyboard_press_resolves_key_and_modifiers():
    tab = MagicMock()
    tab.keyboard = MagicMock(press=AsyncMock())
    with patch('pydoll_cli.commands.keyboard.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'keyboard', 'press', 'A',
             '--modifiers', 'CONTROL,SHIFT', '--interval-ms', '50'],
        )
    assert result.exit_code == 0, result.stdout
    args, kwargs = tab.keyboard.press.call_args
    assert args == (Key.A,)
    # CTRL=2, SHIFT=8 — pass the OR'd int (KeyModifier IntEnum can't represent 10).
    assert kwargs['modifiers'] == int(KeyModifier.CTRL) | int(KeyModifier.SHIFT)
    assert kwargs['interval'] == 0.05


def test_keyboard_press_unknown_key_exits_2():
    tab = MagicMock()
    tab.keyboard = MagicMock(press=AsyncMock())
    with patch('pydoll_cli.commands.keyboard.open_browser', _stub(tab)):
        result = runner.invoke(app, ['keyboard', 'press', 'NOT_A_KEY'])
    assert result.exit_code == 2


def test_keyboard_hotkey_two_keys():
    tab = MagicMock()
    tab.keyboard = MagicMock(hotkey=AsyncMock())
    with patch('pydoll_cli.commands.keyboard.open_browser', _stub(tab)):
        result = runner.invoke(app, ['--output', 'json', 'keyboard', 'hotkey', 'CONTROL', 'S'])
    assert result.exit_code == 0, result.stdout
    tab.keyboard.hotkey.assert_awaited_once_with(Key.CONTROL, Key.S)


def test_keyboard_hotkey_too_many_exits_2():
    tab = MagicMock()
    tab.keyboard = MagicMock(hotkey=AsyncMock())
    with patch('pydoll_cli.commands.keyboard.open_browser', _stub(tab)):
        result = runner.invoke(
            app, ['keyboard', 'hotkey', 'CONTROL', 'SHIFT', 'ALT', 'A'],
        )
    assert result.exit_code == 2


def test_keyboard_type_humanize_passes_through():
    tab = MagicMock()
    tab.keyboard = MagicMock(type_text=AsyncMock())
    with patch('pydoll_cli.commands.keyboard.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'keyboard', 'type', 'hello world', '--humanize'],
        )
    assert result.exit_code == 0, result.stdout
    tab.keyboard.type_text.assert_awaited_once_with('hello world', humanize=True)


# ---- mouse -----------------------------------------------------------------


def test_mouse_click_default_left():
    tab = MagicMock()
    tab.mouse = MagicMock(click=AsyncMock(), double_click=AsyncMock())
    with patch('pydoll_cli.commands.mouse.open_browser', _stub(tab)):
        result = runner.invoke(app, ['--output', 'json', 'mouse', 'click', '100', '200'])
    assert result.exit_code == 0, result.stdout
    tab.mouse.click.assert_awaited_once_with(100.0, 200.0, button=MouseButton.LEFT, humanize=False)


def test_mouse_click_double_uses_double_click():
    tab = MagicMock()
    tab.mouse = MagicMock(click=AsyncMock(), double_click=AsyncMock())
    with patch('pydoll_cli.commands.mouse.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'mouse', 'click', '50', '50',
             '--double', '--button', 'right', '--humanize'],
        )
    assert result.exit_code == 0, result.stdout
    tab.mouse.double_click.assert_awaited_once_with(
        50.0, 50.0, button=MouseButton.RIGHT, humanize=True,
    )


def test_mouse_drag_passes_all_coords():
    tab = MagicMock()
    tab.mouse = MagicMock(drag=AsyncMock())
    with patch('pydoll_cli.commands.mouse.open_browser', _stub(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'mouse', 'drag', '10', '20', '100', '200'],
        )
    assert result.exit_code == 0, result.stdout
    tab.mouse.drag.assert_awaited_once_with(10.0, 20.0, 100.0, 200.0, humanize=False)


# ---- scroll ----------------------------------------------------------------


def test_scroll_no_mode_exits_2():
    tab = MagicMock()
    tab.scroll = MagicMock(by=AsyncMock(), to_bottom=AsyncMock())
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(app, ['scroll'])
    assert result.exit_code == 2


def test_scroll_two_modes_exits_2():
    tab = MagicMock()
    tab.scroll = MagicMock(by=AsyncMock())
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(app, ['scroll', '--by-y', '100', '--to-y', '0'])
    assert result.exit_code == 2


def test_scroll_by_y_positive_goes_down():
    tab = MagicMock()
    tab.scroll = MagicMock(by=AsyncMock())
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(app, ['--output', 'json', 'scroll', '--by-y', '500'])
    assert result.exit_code == 0, result.stdout
    tab.scroll.by.assert_awaited_once_with(ScrollPosition.DOWN, 500, humanize=False)


def test_scroll_by_y_negative_goes_up():
    tab = MagicMock()
    tab.scroll = MagicMock(by=AsyncMock())
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(
            app, ['--output', 'json', 'scroll', '--by-y', '-300', '--humanize'],
        )
    assert result.exit_code == 0, result.stdout
    tab.scroll.by.assert_awaited_once_with(ScrollPosition.UP, 300, humanize=True)


def test_scroll_to_y_uses_window_scrollto():
    tab = MagicMock()
    tab.execute_script = AsyncMock(return_value={'result': {'result': {'value': None}}})
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(app, ['--output', 'json', 'scroll', '--to-y', '0'])
    assert result.exit_code == 0, result.stdout
    args, _ = tab.execute_script.call_args
    assert 'window.scrollTo' in args[0]
    assert 'top: 0' in args[0]


def test_scroll_to_selector_calls_scroll_into_view():
    element = MagicMock()
    element.scroll_into_view = AsyncMock()
    tab = MagicMock()
    tab.query = AsyncMock(return_value=element)
    with patch('pydoll_cli.commands.scroll.open_browser', _stub(tab)):
        result = runner.invoke(
            app, ['--output', 'json', 'scroll', '--to-selector', '.footer'],
        )
    assert result.exit_code == 0, result.stdout
    element.scroll_into_view.assert_awaited_once()
