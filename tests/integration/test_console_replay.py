"""Integration test for retroactive console capture. Requires a real browser.

Run with: ``uv run pytest -m integration -q``

The whole `console` design rests on one Chrome behavior: console history is
buffered per document and replayed to *any* client that enables the Runtime and
Log domains, including a connection that did not exist when the page loaded.
This test is the regression guard for that — it loads a page, tears the
connection down completely, then reads the history from a fresh invocation.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from pydoll.browser import Chrome
from typer.testing import CliRunner

from pydoll_cli import session as session_mod
from pydoll_cli.cli import app
from pydoll_cli.context import GlobalOptions

pytestmark = pytest.mark.integration

runner = CliRunner()

SESSION_NAME = 'pydoll-cli-itest-console'

PAGE = """<!doctype html>
<title>console fixture</title>
<img src="does-not-exist.png">
<script>
console.log('log-line');
console.info('info-line');
console.warn('warn-line');
console.error('error-line');
console.log({shape: 'object'});
undefinedFn();
</script>
"""


@pytest.fixture
def loaded_session(tmp_path: Path):
    """A detached headless session with the fixture page loaded, connection closed."""
    page = tmp_path / 'console.html'
    page.write_text(PAGE)
    opts = GlobalOptions(headless=True)

    session_mod.stop_quiet(SESSION_NAME)
    state = asyncio.run(session_mod.start(SESSION_NAME, opts))

    async def _load() -> None:
        browser = Chrome()
        try:
            await browser.connect(state.ws_url)
            tabs = await browser.get_opened_tabs()
            tab = tabs[0] if tabs else await browser.new_tab()
            await tab.go_to(page.as_uri())
            # Give the img 404 and the uncaught error time to land in the buffer.
            await asyncio.sleep(1.0)
        finally:
            await browser.close()

    asyncio.run(_load())
    try:
        yield state
    finally:
        # stop_quiet kills the browser and removes the state file, but leaves the
        # session's Chrome profile behind — ~7MB per run in the user's real cache
        # dir. Tests clean up after themselves.
        session_mod.stop_quiet(SESSION_NAME)
        shutil.rmtree(session_mod.sessions_dir() / SESSION_NAME, ignore_errors=True)


def _console_logs(*extra: str) -> list[dict]:
    result = runner.invoke(
        app,
        ['--session', SESSION_NAME, '--output', 'json', 'console', 'logs', *extra],
    )
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_history_replays_to_a_fresh_connection(loaded_session):
    """No prior arming: the CLI attaches after the fact and still sees everything."""
    records = _console_logs()
    texts = [r['text'] for r in records]

    assert 'log-line' in texts
    assert 'info-line' in texts
    assert 'warn-line' in texts
    assert 'error-line' in texts

    by_level = {r['level'] for r in records}
    assert {'log', 'info', 'warning', 'error'} <= by_level

    # Uncaught JS error — Runtime.exceptionThrown, not a console API call.
    exceptions = [r for r in records if r['source'] == 'exception']
    assert exceptions, records
    assert 'undefinedFn' in exceptions[0]['text']

    # Browser-generated message the Runtime domain never reports.
    entries = [r for r in records if r['source'] not in ('console-api', 'exception')]
    assert entries, records
    assert any('does-not-exist.png' in (r['url'] or '') for r in entries)

    # Object args must not collapse to None.
    assert not any(r['text'] in (None, 'None', '') for r in records)

    # Merged Runtime + Log bursts come out in timestamp order.
    stamps = [r['timestamp'] for r in records]
    assert stamps == sorted(stamps)


def test_replay_is_non_destructive(loaded_session):
    """Reading twice returns the same history — enabling again re-delivers it."""
    first = _console_logs()
    second = _console_logs()
    assert [r['text'] for r in first] == [r['text'] for r in second]


def test_clear_empties_the_replay_buffer(loaded_session):
    """--clear discards the history so a later read starts fresh."""
    assert _console_logs()
    assert _console_logs('--clear')
    assert _console_logs() == []


def test_filters_narrow_the_result(loaded_session):
    errors = _console_logs('--level', 'error')
    assert errors
    assert {r['level'] for r in errors} == {'error'}

    matched = _console_logs('--filter', 'warn-line')
    assert [r['text'] for r in matched] == ['warn-line']

    only_api = _console_logs('--kind', 'console-api')
    assert only_api
    assert {r['source'] for r in only_api} == {'console-api'}
