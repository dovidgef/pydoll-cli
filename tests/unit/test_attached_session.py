"""Tests for attached-session behavior: tab adoption, leak prevention, stop semantics.

Covers two bugs and the new --tab-url adoption flow:
- Bug 1: shared-profile session start always created a new tab even when the
  requested URL was already open.
- Bug 2: _open_attached materialized a blank tab when the persisted target_id
  was gone, even when the caller was about to switch via --tab-url/--tab.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pydoll_cli import async_runner
from pydoll_cli import session as session_mod
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError
from pydoll_cli.session import SessionState

# ---- fakes ---------------------------------------------------------------


class _FakeTab:
    """Minimal stand-in for pydoll's Tab.

    Mirrors the bits of the real Tab that session/async_runner code touches:
    the ``_target_id`` attribute, the async ``current_url`` property, and
    awaitable ``go_to`` / ``close`` methods.
    """

    def __init__(self, target_id: str, url: str = 'about:blank'):
        self._target_id = target_id
        self._url = url
        self.go_to = AsyncMock()
        self.close = AsyncMock()

    @property
    async def current_url(self) -> str:
        return self._url


def _fake_browser(open_tabs: list[_FakeTab], new_tab_target: str = 'new-tab-id') -> MagicMock:
    """Build a MagicMock browser whose async methods behave like pydoll's."""
    browser = MagicMock()
    browser.connect = AsyncMock()
    browser.close = AsyncMock()
    browser.get_opened_tabs = AsyncMock(return_value=open_tabs)
    browser.create_browser_context = AsyncMock(return_value='ctx-id')
    browser.delete_browser_context = AsyncMock()

    async def _new_tab(*_args, **_kwargs):
        new = _FakeTab(new_tab_target, url='about:blank')
        open_tabs.append(new)
        return new

    browser.new_tab = AsyncMock(side_effect=_new_tab)
    return browser


@pytest.fixture
def opts() -> GlobalOptions:
    return GlobalOptions(browser='wavebox')


@pytest.fixture
def isolated_state_dir(monkeypatch, tmp_path: Path):
    """Redirect session state writes to a tmp dir."""
    monkeypatch.setattr(session_mod, 'sessions_dir', lambda: tmp_path)
    return tmp_path


# ---- Bug 1: start_attached reuse semantics --------------------------------


def test_start_attached_share_profile_reuses_existing_tab(opts, isolated_state_dir):
    """--share-profile + --url X with X already open → adopt the existing tab."""
    existing = _FakeTab('existing-tid', url='https://example.com/page')
    browser = _fake_browser([existing])

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        state = asyncio.run(
            session_mod.start_attached(
                'sess',
                'ws://127.0.0.1:9222/devtools/browser/abc',
                opts,
                initial_url='example.com',
                use_incognito=False,
            )
        )

    browser.new_tab.assert_not_called()
    existing.go_to.assert_not_called()
    assert state.target_id == 'existing-tid'
    assert state.created_target is False
    assert state.browser_context_id is None


def test_start_attached_share_profile_creates_when_no_match(opts, isolated_state_dir):
    """--share-profile + --url X with no matching tab → create new tab and navigate."""
    other = _FakeTab('other-tid', url='https://different.com/')
    browser = _fake_browser([other], new_tab_target='created-tid')

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        state = asyncio.run(
            session_mod.start_attached(
                'sess',
                'ws://127.0.0.1:9222/devtools/browser/abc',
                opts,
                initial_url='https://example.com',
                use_incognito=False,
            )
        )

    browser.new_tab.assert_awaited_once()
    # The newly-created tab is the last one appended.
    created = next(t for t in browser.get_opened_tabs.return_value if t._target_id == 'created-tid')
    created.go_to.assert_awaited_once_with('https://example.com')
    assert state.target_id == 'created-tid'
    assert state.created_target is True


def test_start_attached_share_profile_no_url_creates_blank(opts, isolated_state_dir):
    """--share-profile with neither --url nor --tab-url → blank tab, created."""
    browser = _fake_browser([], new_tab_target='blank-tid')

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        state = asyncio.run(
            session_mod.start_attached(
                'sess',
                'ws://127.0.0.1:9222/devtools/browser/abc',
                opts,
                use_incognito=False,
            )
        )

    browser.new_tab.assert_awaited_once()
    assert state.created_target is True
    assert state.target_id == 'blank-tid'


# ---- New: tab_url adopt-only path -----------------------------------------


def test_start_attached_tab_url_adopts_match(opts, isolated_state_dir):
    target = _FakeTab('target-tid', url='https://github.com/anthropics/claude-code')
    other = _FakeTab('other-tid', url='https://news.ycombinator.com/')
    browser = _fake_browser([other, target])

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        state = asyncio.run(
            session_mod.start_attached(
                'sess',
                'ws://127.0.0.1:9222/devtools/browser/abc',
                opts,
                tab_url='github.com/anthropics',
                use_incognito=False,
            )
        )

    browser.new_tab.assert_not_called()
    assert state.target_id == 'target-tid'
    assert state.created_target is False


def test_start_attached_tab_url_no_match_raises(opts, isolated_state_dir):
    other = _FakeTab('other-tid', url='https://example.com/')
    browser = _fake_browser([other])

    with (
        patch('pydoll_cli.session.Chrome', return_value=browser),
        pytest.raises(CliError) as excinfo,
    ):
        asyncio.run(
            session_mod.start_attached(
                'sess',
                'ws://127.0.0.1:9222/devtools/browser/abc',
                opts,
                tab_url='nope.example',
                use_incognito=False,
            )
        )

    assert excinfo.value.exit_code == 4
    browser.new_tab.assert_not_called()


# ---- Bug 2: _open_attached blank-tab leak ---------------------------------


def _write_state(tmp_path: Path, **overrides) -> SessionState:
    state = SessionState(
        name='sess',
        pid=0,
        port=9222,
        ws_url='ws://127.0.0.1:9222/devtools/browser/abc',
        user_data_dir='',
        browser='wavebox',
        binary='',
        started_at=0.0,
        attached=True,
        browser_context_id=None,
        target_id='persisted-tid',
        created_target=True,
    )
    for k, v in overrides.items():
        setattr(state, k, v)
    (tmp_path / f'{state.name}.json').write_text(state.to_json())
    return state


def test_open_attached_skips_blank_when_caller_will_switch(isolated_state_dir):
    """Persisted tab gone + --tab-url specified → no blank tab created; re-pin."""
    state = _write_state(isolated_state_dir)
    target = _FakeTab('resolved-tid', url='https://example.com/x')
    browser = _fake_browser([target])
    opts = GlobalOptions(session='sess', tab_url='example.com')

    async def _run():
        async with async_runner._open_attached(opts, state) as (_b, tab):
            return tab

    with patch('pydoll_cli.async_runner.Chrome', return_value=browser):
        tab = asyncio.run(_run())

    browser.new_tab.assert_not_called()
    assert tab is target

    # State was re-pinned to the resolved tab and marked adopted.
    on_disk = json.loads((isolated_state_dir / 'sess.json').read_text())
    assert on_disk['target_id'] == 'resolved-tid'
    assert on_disk['created_target'] is False


def test_open_attached_creates_blank_when_no_switch_specified(isolated_state_dir):
    """Persisted tab gone, no --tab-url/--tab → fall back to blank tab (current safety net)."""
    state = _write_state(isolated_state_dir)
    other = _FakeTab('other-tid', url='https://elsewhere.com/')
    browser = _fake_browser([other], new_tab_target='blank-fallback')
    opts = GlobalOptions(session='sess')

    async def _run():
        async with async_runner._open_attached(opts, state) as (_b, tab):
            return tab

    with patch('pydoll_cli.async_runner.Chrome', return_value=browser):
        asyncio.run(_run())

    browser.new_tab.assert_awaited_once()

    on_disk = json.loads((isolated_state_dir / 'sess.json').read_text())
    assert on_disk['target_id'] == 'blank-fallback'
    assert on_disk['created_target'] is True


def test_open_attached_pinned_tab_present_no_recreate(isolated_state_dir):
    """Persisted tab is still there → no new_tab call, no re-pin."""
    state = _write_state(isolated_state_dir)
    pinned = _FakeTab('persisted-tid', url='https://kept.com/')
    browser = _fake_browser([pinned])
    opts = GlobalOptions(session='sess')

    async def _run():
        async with async_runner._open_attached(opts, state) as (_b, tab):
            return tab

    with patch('pydoll_cli.async_runner.Chrome', return_value=browser):
        tab = asyncio.run(_run())

    browser.new_tab.assert_not_called()
    assert tab is pinned

    on_disk = json.loads((isolated_state_dir / 'sess.json').read_text())
    assert on_disk['target_id'] == 'persisted-tid'
    assert on_disk['created_target'] is True  # untouched


# ---- _stop_attached: opt-in close ----------------------------------------


def test_stop_attached_default_leaves_tab_alone():
    state = SessionState(
        name='sess',
        pid=0,
        port=9222,
        ws_url='ws://x',
        user_data_dir='',
        browser='wavebox',
        binary='',
        started_at=0.0,
        attached=True,
        browser_context_id=None,
        target_id='pinned-tid',
        created_target=False,
    )
    pinned = _FakeTab('pinned-tid', url='https://example.com/')
    browser = _fake_browser([pinned])

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        asyncio.run(session_mod._stop_attached(state, close_tab=False))

    pinned.close.assert_not_called()
    browser.delete_browser_context.assert_not_called()


def test_stop_attached_close_tab_closes_pinned():
    state = SessionState(
        name='sess',
        pid=0,
        port=9222,
        ws_url='ws://x',
        user_data_dir='',
        browser='wavebox',
        binary='',
        started_at=0.0,
        attached=True,
        browser_context_id=None,
        target_id='pinned-tid',
        created_target=True,
    )
    pinned = _FakeTab('pinned-tid', url='https://example.com/')
    other = _FakeTab('other-tid', url='https://other.com/')
    browser = _fake_browser([other, pinned])

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        asyncio.run(session_mod._stop_attached(state, close_tab=True))

    pinned.close.assert_awaited_once()
    other.close.assert_not_called()


def test_stop_attached_incognito_always_deletes_context():
    state = SessionState(
        name='sess',
        pid=0,
        port=9222,
        ws_url='ws://x',
        user_data_dir='',
        browser='wavebox',
        binary='',
        started_at=0.0,
        attached=True,
        browser_context_id='ctx-id',
        target_id='pinned-tid',
        created_target=True,
    )
    browser = _fake_browser([])

    with patch('pydoll_cli.session.Chrome', return_value=browser):
        asyncio.run(session_mod._stop_attached(state, close_tab=False))

    browser.delete_browser_context.assert_awaited_once_with('ctx-id')
