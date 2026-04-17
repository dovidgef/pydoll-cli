"""Async bridge: convert a typer callback into an async-run wrapper,
and provide the `open_browser` context manager that uniformly handles
`--connect`, `--session`, and fresh-launch modes.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import typer
from pydoll.browser import Chrome
from pydoll.browser.chromium.base import Browser
from pydoll.browser.chromium.edge import Edge

from pydoll_cli import session as session_mod
from pydoll_cli.context import GlobalOptions
from pydoll_cli.options_builder import build_options
from pydoll_cli.output import EXIT_INTERRUPTED, CliError


def run_async(coro_fn: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Any]:
    """Decorate a typer command so its async body runs inside `asyncio.run`."""

    @functools.wraps(coro_fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return asyncio.run(coro_fn(*args, **kwargs))
        except KeyboardInterrupt as e:
            raise typer.Exit(EXIT_INTERRUPTED) from e
        except CliError as e:
            # Render to stderr here so every command funnel shares the path.
            typer.echo(f'error: {e}', err=True)
            raise typer.Exit(e.exit_code) from e

    return wrapper


@asynccontextmanager
async def open_browser(opts: GlobalOptions) -> AsyncIterator[tuple[Any, Any]]:
    """Yield ``(browser, tab)`` appropriate for this invocation.

    Mode precedence: ``--connect`` > ``--session`` > fresh launch.
    """
    # Attached session: reuse the persisted tab (and incognito context if any).
    if opts.session and not opts.connect:
        state = session_mod.load(opts.session)
        if state.attached:
            async with _open_attached(opts, state) as pair:
                yield pair
                return

    ws_url = _resolve_ws_url(opts)
    browser: Browser
    if ws_url is not None:
        browser = Chrome()
        default_tab = await browser.connect(ws_url)
        context_id: str | None = None
        tab: Any
        try:
            if opts.fresh:
                # New incognito browser context + new tab in it. Leaves existing tabs alone.
                context_id = await browser.create_browser_context()
                tab = await browser.new_tab(browser_context_id=context_id)
            elif opts.new_tab:
                tab = await browser.new_tab()
            else:
                tab = await _maybe_switch_tab(browser, default_tab, opts)
            yield browser, tab
        finally:
            if context_id is not None:
                with contextlib.suppress(Exception):
                    await browser.delete_browser_context(context_id)
            await browser.close()
        return

    # Fresh launch.
    options = build_options(opts)
    browser = (
        Edge(options=options, connection_port=opts.cdp_port)
        if opts.browser == 'edge'
        else Chrome(options=options, connection_port=opts.cdp_port)
    )
    async with browser:
        tab = await browser.start()
        tab = await _maybe_switch_tab(browser, tab, opts)
        yield browser, tab


def _resolve_ws_url(opts: GlobalOptions) -> str | None:
    if opts.connect:
        return opts.connect
    if opts.session:
        state = session_mod.load(opts.session)
        return state.ws_url
    return None


@asynccontextmanager
async def _open_attached(opts: GlobalOptions, state: Any) -> AsyncIterator[tuple[Any, Any]]:
    """Reuse a persisted attached session: connect, find our incognito tab.

    If the tab was closed externally, create a new one in the same context and
    update the state file with its new target_id.
    """
    browser = Chrome()
    try:
        await browser.connect(state.ws_url)
        tab = None
        tabs = await browser.get_opened_tabs()
        for t in tabs:
            if t._target_id == state.target_id:
                tab = t
                break
        if tab is None:
            # Tab was closed; spawn a fresh one in the same context (incognito
            # or default, depending on how the session was started).
            if state.browser_context_id:
                tab = await browser.new_tab(
                    browser_context_id=state.browser_context_id,
                )
            else:
                tab = await browser.new_tab()
            state.target_id = tab._target_id
            session_mod.state_path(state.name).write_text(state.to_json())
        # Apply --tab-url/--tab overrides if the caller wants a different tab
        # within the same attached browser (unlikely but supported).
        tab = await _maybe_switch_tab(browser, tab, opts)
        yield browser, tab
    finally:
        await browser.close()


async def _maybe_switch_tab(browser: Any, default_tab: Any, opts: GlobalOptions) -> Any:
    """When attaching to an existing browser, honor --tab / --tab-url."""
    if opts.tab is None and opts.tab_url is None:
        return default_tab
    tabs = await browser.get_opened_tabs()
    if not tabs:
        return default_tab
    if opts.tab_url is not None:
        for tab in tabs:
            url = await tab.current_url
            if opts.tab_url in url:
                return tab
        raise CliError(f'No open tab matched URL containing {opts.tab_url!r}.', 4)
    if opts.tab is not None:
        if opts.tab < 0 or opts.tab >= len(tabs):
            raise CliError(
                f'--tab {opts.tab} out of range (have {len(tabs)} tabs).',
                2,
            )
        return tabs[opts.tab]
    return default_tab
