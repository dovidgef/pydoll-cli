"""Unit tests for the `wait` command — mode dispatch + helper behavior."""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydoll.protocol.network.events import NetworkEvent
from pydoll.protocol.page.events import PageEvent
from typer.testing import CliRunner

from pydoll_cli.async_runner import wait_for_event
from pydoll_cli.cli import app

runner = CliRunner()


class _Tab:
    """Hand-rolled tab stub: mirrors the slice of pydoll.Tab the wait command uses."""

    def __init__(self) -> None:
        self.go_to = AsyncMock()
        self.query = AsyncMock(return_value=MagicMock())
        self.execute_script = AsyncMock(
            return_value={
                'result': {
                    'result': {'type': 'object', 'value': {'ok': True, 'count': 5, 'ms': 100}}
                }
            },
        )
        self.enable_page_events = AsyncMock()
        self.disable_page_events = AsyncMock()
        self.enable_network_events = AsyncMock()
        self.disable_network_events = AsyncMock()
        self.on = AsyncMock(return_value=1)
        self.remove_callback = AsyncMock()
        self.page_events_enabled = False
        self.network_events_enabled = False

    @property
    def current_url(self):
        async def _coro() -> str:
            return 'https://x.com/dashboard/home'

        return _coro()


def _stub_browser(tab: _Tab) -> contextlib.AbstractAsyncContextManager:
    @contextlib.asynccontextmanager
    async def _ctx(_opts):
        yield (MagicMock(), tab)

    return _ctx


# ---- Mode validation -------------------------------------------------------


def test_wait_no_mode_exits_2():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(app, ['--output', 'json', 'wait'])
    assert result.exit_code == 2


def test_wait_two_modes_exits_2():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--selector', '.x', '--js', 'true'],
        )
    assert result.exit_code == 2


# ---- Mode-specific routing -------------------------------------------------


def test_wait_selector_calls_tab_query():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--selector', '.content', '--wait', '5'],
        )
    assert result.exit_code == 0, result.stdout
    tab.query.assert_awaited_once_with('.content', timeout=5, raise_exc=False)


def test_wait_selector_not_found_exits_3():
    tab = _Tab()
    tab.query = AsyncMock(return_value=None)
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--selector', '.content', '--wait', '1'],
        )
    assert result.exit_code == 3, (result.exit_code, result.stdout)


def test_wait_url_contains_returns_immediately_when_already_match():
    tab = _Tab()
    # The stub _Tab returns 'https://x.com/dashboard/home' which contains '/dashboard'.
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--url-contains', '/dashboard'],
        )
    assert result.exit_code == 0, result.stdout
    tab.enable_page_events.assert_not_called()


def test_wait_page_event_subscribes():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--page-event', 'load', '--wait', '0.5'],
        )
    # Mock can't fire CDP events on its own — we expect timeout (exit 3) here.
    # What we're testing is that the right wiring happened before that timeout.
    assert result.exit_code == 3, (result.exit_code, result.stdout)
    tab.enable_page_events.assert_awaited_once()
    args, _ = tab.on.call_args
    assert args[0] == PageEvent.LOAD_EVENT_FIRED.value


def test_wait_page_event_invalid_exits_2():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--page-event', 'bogus', '--wait', '1'],
        )
    assert result.exit_code == 2


def test_wait_page_event_load_resolves_when_already_complete():
    tab = _Tab()
    tab.execute_script = AsyncMock(
        return_value={'result': {'result': {'type': 'string', 'value': 'complete'}}},
    )
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--page-event', 'load', '--wait', '0.5'],
        )
    assert result.exit_code == 0, result.stdout
    assert '"already": "complete"' in result.stdout
    tab.enable_page_events.assert_not_called()


def test_wait_page_event_dom_content_resolves_when_interactive():
    tab = _Tab()
    tab.execute_script = AsyncMock(
        return_value={'result': {'result': {'type': 'string', 'value': 'interactive'}}},
    )
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--page-event', 'dom-content', '--wait', '0.5'],
        )
    assert result.exit_code == 0, result.stdout
    assert '"already": "interactive"' in result.stdout
    tab.enable_page_events.assert_not_called()


def test_wait_page_event_load_subscribes_when_loading():
    tab = _Tab()
    tab.execute_script = AsyncMock(
        return_value={'result': {'result': {'type': 'string', 'value': 'loading'}}},
    )
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--page-event', 'load', '--wait', '0.3'],
        )
    # Mock can't fire CDP events — falls through to listener and times out.
    assert result.exit_code == 3, (result.exit_code, result.stdout)
    tab.enable_page_events.assert_awaited_once()


def test_wait_network_idle_subscribes_to_three_events():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            [
                '--output',
                'json',
                'wait',
                '--network-idle',
                '--idle-ms',
                '50',
                '--wait',
                '1',
            ],
        )
    # Either ready (no requests => instant idle) or timeout — both keep the
    # registration shape correct. Test the subscriptions, not the outcome.
    assert tab.enable_network_events.await_count == 1
    subscribed_events = {call.args[0] for call in tab.on.call_args_list}
    assert NetworkEvent.REQUEST_WILL_BE_SENT.value in subscribed_events
    assert NetworkEvent.LOADING_FINISHED.value in subscribed_events
    assert NetworkEvent.LOADING_FAILED.value in subscribed_events
    assert result.exit_code in (0, 3)


def test_wait_js_runs_promise_with_await():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--js', '1+1', '--wait', '1'],
        )
    assert result.exit_code == 0, result.stdout
    args, kwargs = tab.execute_script.call_args
    assert 'new Promise' in args[0]
    assert kwargs.get('await_promise') is True


def test_wait_stable_ids_validates_format():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--stable-ids', 'no-pipe', '--wait', '1'],
        )
    assert result.exit_code == 2


def test_wait_stable_ids_runs_promise():
    tab = _Tab()
    with patch('pydoll_cli.commands.wait.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'wait', '--stable-ids', '.row|data-id', '--wait', '1'],
        )
    assert result.exit_code == 0, result.stdout
    args, kwargs = tab.execute_script.call_args
    assert 'data-id' in args[0]
    assert kwargs.get('await_promise') is True


# ---- Helper: wait_for_event ------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_event_resolves_on_first_match():
    tab = MagicMock()
    callback_holder: list = []

    async def fake_on(_event, cb):
        callback_holder.append(cb)
        return 42

    tab.on = AsyncMock(side_effect=fake_on)
    tab.remove_callback = AsyncMock()

    async def fire():
        # Wait for the listener to register, then deliver a synthetic event.
        for _ in range(50):
            if callback_holder:
                break
            await asyncio.sleep(0)
        await callback_holder[0]({'method': 'X', 'params': {'foo': 1}})

    await asyncio.gather(fire(), wait_for_event(tab, 'X', timeout=2))

    tab.remove_callback.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_wait_for_event_times_out():
    tab = MagicMock()
    tab.on = AsyncMock(return_value=1)
    tab.remove_callback = AsyncMock()

    with pytest.raises(asyncio.TimeoutError):
        await wait_for_event(tab, 'X', timeout=0.05)
    tab.remove_callback.assert_awaited_once_with(1)
