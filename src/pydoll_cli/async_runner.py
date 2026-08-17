"""Async bridge: convert a typer callback into an async-run wrapper,
and provide the `open_browser` context manager that uniformly handles
`--connect`, `--session`, and fresh-launch modes.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

import typer
from pydoll.browser import Chrome
from pydoll.browser.chromium.base import Browser
from pydoll.browser.chromium.edge import Edge

from pydoll_cli import session as session_mod
from pydoll_cli.context import GlobalOptions
from pydoll_cli.options_builder import build_options
from pydoll_cli.output import EXIT_INTERRUPTED, EXIT_NO_SESSION, CliError
from pydoll_cli.targets import (
    is_internal_url,
    tab_url,
    target_info_map,
    visible_tabs,
    visible_tabs_with_urls,
)


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
                default_tab = await _non_internal_default(browser, default_tab, opts)
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


def _dead_pin_message(name: str) -> str:
    """Explain a dead pin and the two ways out, without guessing which they want."""
    return (
        f'session {name!r} is pinned to a tab that no longer exists — it was closed, '
        'or the browser restarted. Refusing to open a replacement tab in your browser. '
        f'Point it at a live tab with --tab-url SUBSTR (that re-pins the session), or '
        f'restart it: pydoll-cli session stop {name}'
    )


@asynccontextmanager
async def _open_attached(opts: GlobalOptions, state: Any) -> AsyncIterator[tuple[Any, Any]]:
    """Reuse a persisted attached session: connect, find our pinned tab.

    If the persisted tab is gone and the caller is going to pick a tab via
    ``--tab-url``/``--tab``, skip the replacement-tab fallback — the caller is
    about to resolve one anyway. Re-pin ``state.target_id`` to whatever the
    caller actually selects so subsequent calls find it directly.

    When the pin is dead and the caller named no alternative, recreate the tab
    only when it costs nothing: an incognito session's tab lives in a browser
    context we created, and ``session stop`` disposes that context wholesale.
    A shared-profile session has no context of ours — a replacement tab would
    land in the user's real browser and outlive the session (``session stop``
    leaves it by default), so we refuse and say what to do instead.
    """
    browser = Chrome()
    try:
        await browser.connect(state.ws_url)
        tabs = await browser.get_opened_tabs()
        tab = next((t for t in tabs if t._target_id == state.target_id), None)
        caller_will_switch = opts.tab_url is not None or opts.tab is not None

        if tab is None and not caller_will_switch:
            if not state.browser_context_id:
                raise CliError(_dead_pin_message(state.name), EXIT_NO_SESSION)
            try:
                tab = await browser.new_tab(
                    browser_context_id=state.browser_context_id,
                )
            except Exception as e:
                # Context is gone too (browser restarted) — nothing to heal into.
                raise CliError(_dead_pin_message(state.name), EXIT_NO_SESSION) from e
            state.target_id = tab._target_id
            state.created_target = True
            session_mod.state_path(state.name).write_text(state.to_json())

        # Hand whatever we have (possibly None) to the switcher; if --tab-url
        # is set it will resolve to the requested tab. The fallback picks the
        # first *visible* tab — a DevTools window must never be adopted by
        # accident — but the target_id lookup above stays unfiltered, so a
        # deliberately pinned chrome:// tab keeps resolving.
        default = tab
        if default is None:
            candidates = await visible_tabs(browser, include_internal=opts.include_internal)
            default = candidates[0] if candidates else None
        tab = await _maybe_switch_tab(browser, default, opts)

        # Re-pin to whatever the caller actually selected so the blank-tab
        # path doesn't trigger again on the next call. Mark adopted.
        if tab is not None and getattr(tab, '_target_id', None) != state.target_id:
            state.target_id = tab._target_id
            state.created_target = False
            session_mod.state_path(state.name).write_text(state.to_json())

        yield browser, tab
    finally:
        await browser.close()


async def wait_for_event(
    tab: Any,
    event_name: str,
    *,
    predicate: Callable[[dict[str, Any]], bool]
    | Callable[[dict[str, Any]], Awaitable[bool]]
    | None = None,
    timeout: float,
) -> dict[str, Any]:
    """Subscribe to a CDP event on ``tab``; resolve with the first matching event.

    ``predicate`` may be sync or async; return ``True`` to accept the event.
    Raises ``asyncio.TimeoutError`` if no matching event arrives within ``timeout``.
    The callback is removed before returning, even on timeout/cancellation.

    The corresponding event domain (Page, Network, etc.) must already be enabled
    on ``tab`` before calling this — otherwise events never fire.
    """
    fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()

    async def callback(event: dict[str, Any]) -> None:
        if fut.done():
            return
        try:
            if predicate is None:
                accept: bool = True
            else:
                result = predicate(event)
                accept = bool(await result) if asyncio.iscoroutine(result) else bool(result)
        except Exception:
            return
        if accept and not fut.done():
            fut.set_result(event)

    callback_id = await tab.on(event_name, callback)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        with contextlib.suppress(Exception):
            await tab.remove_callback(callback_id)


async def _non_internal_default(browser: Any, default_tab: Any, opts: GlobalOptions) -> Any:
    """Keep pydoll's connect-time default tab off browser-internal targets.

    ``Browser.connect`` hands back ``get_opened_tabs()[0]``, unfiltered — so an
    open DevTools window can become the tab every ``--session`` call drives.
    Only applies when the caller expressed no preference; ``--tab`` /
    ``--tab-url`` are resolved afterwards by ``_maybe_switch_tab``.
    """
    if opts.include_internal or default_tab is None:
        return default_tab
    if opts.tab is not None or opts.tab_url is not None:
        return default_tab
    url = await tab_url(default_tab, await target_info_map(browser))
    if not is_internal_url(url):
        return default_tab
    candidates = await visible_tabs(browser)
    return candidates[0] if candidates else default_tab


async def _maybe_switch_tab(browser: Any, default_tab: Any, opts: GlobalOptions) -> Any:
    """When attaching to an existing browser, honor --tab / --tab-url."""
    if opts.tab is None and opts.tab_url is None:
        return default_tab
    # Explicit selection wins: asking for `--tab-url devtools://` must find the
    # DevTools target, not be protected from it.
    include_internal = opts.include_internal or is_internal_url(opts.tab_url)
    tabs = await visible_tabs_with_urls(browser, include_internal=include_internal)
    if not tabs:
        return default_tab
    if opts.tab_url is not None:
        for tab, url in tabs:
            if url and opts.tab_url in url:
                return tab
        raise CliError(f'No open tab matched URL containing {opts.tab_url!r}.', 4)
    if opts.tab is not None:
        if opts.tab < 0 or opts.tab >= len(tabs):
            raise CliError(
                f'--tab {opts.tab} out of range (have {len(tabs)} tabs).',
                2,
            )
        return tabs[opts.tab][0]
    return default_tab
