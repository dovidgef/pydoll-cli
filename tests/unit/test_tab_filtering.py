"""Tests for browser-internal target filtering.

A detached DevTools window is reported by CDP as a `page` target, so pydoll's
`get_opened_tabs` hands it back like any other tab — and it can land at index 0,
which made `--session NAME` without `--tab-url` drive
`devtools://devtools/bundled/devtools_app.html` instead of the app.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from pydoll_cli import async_runner
from pydoll_cli import session as session_mod
from pydoll_cli.cli import app
from pydoll_cli.commands import tabs as tabs_mod
from pydoll_cli.context import GlobalOptions
from pydoll_cli.targets import is_internal_url, visible_tabs

runner = CliRunner()

DEVTOOLS_URL = 'devtools://devtools/bundled/devtools_app.html'


class _FakeTab:
    def __init__(self, target_id: str, url: str):
        self._target_id = target_id
        self._url = url

    @property
    async def current_url(self) -> str:
        return self._url


class _BrokenTab:
    """A tab whose target is gone; reading current_url raises."""

    def __init__(self, target_id: str = 'broken'):
        self._target_id = target_id

    @property
    async def current_url(self) -> str:
        raise RuntimeError('target detached')


def _browser(tabs: list) -> MagicMock:
    browser = MagicMock()
    browser.get_opened_tabs = AsyncMock(return_value=tabs)
    return browser


@pytest.fixture
def mixed_tabs() -> list:
    return [
        _FakeTab('devtools', DEVTOOLS_URL),
        _FakeTab('app', 'https://app.com/dashboard'),
        _FakeTab('settings', 'chrome://settings'),
        _FakeTab('docs', 'https://docs.com'),
    ]


# ---- is_internal_url -------------------------------------------------------


def test_is_internal_url_flags_devtools_and_chrome():
    assert is_internal_url(DEVTOOLS_URL)
    assert is_internal_url('chrome://settings')


def test_is_internal_url_passes_normal_pages():
    assert not is_internal_url('https://app.com')
    assert not is_internal_url('about:blank')
    assert not is_internal_url('file:///tmp/x.html')
    assert not is_internal_url(None)


# ---- visible_tabs ----------------------------------------------------------


def test_visible_tabs_drops_internal(mixed_tabs):
    tabs = asyncio.run(visible_tabs(_browser(mixed_tabs)))
    assert [t._target_id for t in tabs] == ['app', 'docs']


def test_visible_tabs_keeps_internal_when_requested(mixed_tabs):
    tabs = asyncio.run(visible_tabs(_browser(mixed_tabs), include_internal=True))
    assert [t._target_id for t in tabs] == ['devtools', 'app', 'settings', 'docs']


def test_visible_tabs_skips_tabs_whose_url_raises(mixed_tabs):
    tabs = asyncio.run(visible_tabs(_browser([_BrokenTab(), *mixed_tabs])))
    assert [t._target_id for t in tabs] == ['app', 'docs']


# ---- _maybe_switch_tab index alignment -------------------------------------


def test_tab_index_is_relative_to_visible_tabs(mixed_tabs):
    """`--tab 0` must resolve to what `tabs list` shows at index 0."""
    opts = GlobalOptions(session='s', tab=0)
    chosen = asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert chosen._target_id == 'app'

    opts = GlobalOptions(session='s', tab=1)
    chosen = asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert chosen._target_id == 'docs'


def test_tab_index_out_of_range_counts_visible_only(mixed_tabs):
    """Four open targets, two visible — index 2 is out of range."""
    opts = GlobalOptions(session='s', tab=2)
    with pytest.raises(Exception) as exc:
        asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert 'have 2 tabs' in str(exc.value)


def test_include_internal_restores_full_indexing(mixed_tabs):
    opts = GlobalOptions(session='s', tab=0, include_internal=True)
    chosen = asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert chosen._target_id == 'devtools'


# ---- connect-time default tab ----------------------------------------------


def test_connect_default_swaps_off_an_internal_target(mixed_tabs):
    """pydoll's connect() returns tabs[0] unfiltered — that may be DevTools."""
    devtools = mixed_tabs[0]
    opts = GlobalOptions(session='s')
    chosen = asyncio.run(async_runner._non_internal_default(_browser(mixed_tabs), devtools, opts))
    assert chosen._target_id == 'app'


def test_connect_default_left_alone_when_already_visible(mixed_tabs):
    docs = mixed_tabs[3]
    opts = GlobalOptions(session='s')
    chosen = asyncio.run(async_runner._non_internal_default(_browser(mixed_tabs), docs, opts))
    assert chosen is docs


def test_connect_default_respects_include_internal(mixed_tabs):
    devtools = mixed_tabs[0]
    opts = GlobalOptions(session='s', include_internal=True)
    chosen = asyncio.run(async_runner._non_internal_default(_browser(mixed_tabs), devtools, opts))
    assert chosen is devtools


def test_connect_default_defers_to_explicit_selection(mixed_tabs):
    """--tab / --tab-url are resolved later; don't spend a round trip here."""
    devtools = mixed_tabs[0]
    for opts in (
        GlobalOptions(session='s', tab=1),
        GlobalOptions(session='s', tab_url='docs.com'),
    ):
        chosen = asyncio.run(
            async_runner._non_internal_default(_browser(mixed_tabs), devtools, opts)
        )
        assert chosen is devtools


def test_connect_default_keeps_internal_when_nothing_else_is_open():
    devtools = _FakeTab('devtools', DEVTOOLS_URL)
    opts = GlobalOptions(session='s')
    chosen = asyncio.run(async_runner._non_internal_default(_browser([devtools]), devtools, opts))
    assert chosen is devtools


# ---- explicit selection wins -----------------------------------------------


def test_tab_url_never_matches_internal_by_accident(mixed_tabs):
    """A plain substring must not resolve to a devtools:// target."""
    opts = GlobalOptions(session='s', tab_url='devtools_app')
    with pytest.raises(Exception) as exc:
        asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert 'No open tab matched' in str(exc.value)


def test_explicit_internal_tab_url_is_honored(mixed_tabs):
    opts = GlobalOptions(session='s', tab_url='devtools://')
    chosen = asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert chosen._target_id == 'devtools'

    opts = GlobalOptions(session='s', tab_url='chrome://settings')
    chosen = asyncio.run(async_runner._maybe_switch_tab(_browser(mixed_tabs), None, opts))
    assert chosen._target_id == 'settings'


# ---- session._find_tab_matching --------------------------------------------


def test_find_tab_matching_skips_internal(mixed_tabs):
    found = asyncio.run(session_mod._find_tab_matching(_browser(mixed_tabs), 'devtools'))
    assert found is None


def test_find_tab_matching_honors_explicit_internal_substring(mixed_tabs):
    found = asyncio.run(session_mod._find_tab_matching(_browser(mixed_tabs), 'chrome://settings'))
    assert found is not None
    assert found._target_id == 'settings'


def test_find_tab_matching_still_finds_normal_tabs(mixed_tabs):
    found = asyncio.run(session_mod._find_tab_matching(_browser(mixed_tabs), 'app.com'))
    assert found is not None
    assert found._target_id == 'app'


# ---- `tabs list` indices line up with `--tab N` -----------------------------


@contextlib.contextmanager
def _patched_browser(tabs: list):
    """Replace tabs.open_browser with one yielding a fake browser."""
    browser = _browser(tabs)

    @contextlib.asynccontextmanager
    async def _fake_open(_opts):
        yield browser, None

    with patch.object(tabs_mod, 'open_browser', _fake_open):
        yield


def test_tabs_list_hides_internal_targets(mixed_tabs):
    with _patched_browser(mixed_tabs):
        result = runner.invoke(app, ['--session', 's', '--output', 'json', 'tabs', 'list'])
    assert result.exit_code == 0, result.stdout
    rows = json.loads(result.stdout)
    assert [r['target_id'] for r in rows] == ['app', 'docs']
    # Indices are contiguous and match what `--tab N` resolves to above.
    assert [r['index'] for r in rows] == [0, 1]


def test_tabs_list_shows_everything_with_include_internal(mixed_tabs):
    with _patched_browser(mixed_tabs):
        result = runner.invoke(
            app,
            ['--session', 's', '--include-internal', '--output', 'json', 'tabs', 'list'],
        )
    assert result.exit_code == 0, result.stdout
    rows = json.loads(result.stdout)
    assert [r['target_id'] for r in rows] == ['devtools', 'app', 'settings', 'docs']
