"""`wait` — block until a page condition is satisfied.

Centerpiece of 0.2.0's SPA-hydration story. One flat command, one mode flag
chosen per invocation. Most agents reach for this between `get` and the next
`query`/`click`/`extract` call instead of `sleep N` or `eval` Promise loops.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Annotated, Any

import typer
from pydoll.protocol.network.events import NetworkEvent
from pydoll.protocol.page.events import PageEvent

from pydoll_cli.async_runner import open_browser, run_async, wait_for_event
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import EXIT_TIMEOUT, CliError, Printer

_PAGE_EVENT_MAP: dict[str, str] = {
    'load': PageEvent.LOAD_EVENT_FIRED.value,
    'dom-content': PageEvent.DOM_CONTENT_EVENT_FIRED.value,
    'frame-navigated': PageEvent.FRAME_NAVIGATED.value,
}


def register(app: typer.Typer) -> None:
    @app.command(
        'wait',
        help='Block until a page condition is satisfied (selector / network-idle / URL / event / JS / stable IDs).',
        epilog=(
            'Examples:\n'
            '  pydoll-cli --session s wait --selector ".content"\n'
            '  pydoll-cli --session s wait --selector ".result" --count 5 --wait 30\n'
            '  pydoll-cli --session s wait --network-idle --idle-ms 500 --wait 30\n'
            '  pydoll-cli --session s wait --url-contains /dashboard --wait 10\n'
            '  pydoll-cli --session s wait --page-event dom-content\n'
            '  pydoll-cli --session s wait --js \'document.readyState === "complete"\'\n'
            '  pydoll-cli --session s wait --stable-ids ".result|data-id" --stable-ms 2000 --wait 35\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        selector: Annotated[
            str | None,
            typer.Option('--selector', help='CSS or XPath selector to wait for.'),
        ] = None,
        count: Annotated[
            int,
            typer.Option(
                '--count',
                help='With --selector: wait for AT LEAST this many matches (default 1).',
            ),
        ] = 1,
        network_idle: Annotated[
            bool,
            typer.Option('--network-idle', help='Wait until network in-flight count settles.'),
        ] = False,
        idle_ms: Annotated[
            int,
            typer.Option('--idle-ms', help='With --network-idle: ms of stillness required.'),
        ] = 500,
        max_inflight: Annotated[
            int,
            typer.Option(
                '--max-inflight',
                help='With --network-idle: count requests above this as "active".',
            ),
        ] = 0,
        url_contains: Annotated[
            str | None,
            typer.Option('--url-contains', help='Wait until current URL contains this substring.'),
        ] = None,
        page_event: Annotated[
            str | None,
            typer.Option(
                '--page-event',
                help='Wait for a CDP page event: load | dom-content | frame-navigated.',
            ),
        ] = None,
        js: Annotated[
            str | None,
            typer.Option(
                '--js',
                help='Poll a JS expression every 200ms until it evaluates truthy.',
            ),
        ] = None,
        stable_ids: Annotated[
            str | None,
            typer.Option(
                '--stable-ids',
                help=(
                    'Virtual-scroll stability poll. Format: "SELECTOR|ATTR" (e.g. '
                    '".result|data-id"). Resolves when no new ATTR values appear for '
                    '--stable-ms. Use for aggregator results that progressively populate.'
                ),
            ),
        ] = None,
        stable_ms: Annotated[
            int,
            typer.Option('--stable-ms', help='With --stable-ids: stability window in ms.'),
        ] = 2000,
        wait: Annotated[
            float,
            typer.Option('--wait', help='Overall timeout in seconds (default 30).'),
        ] = 30.0,
    ) -> None:
        modes_set = sum(
            1 for x in (selector, network_idle, url_contains, page_event, js, stable_ids) if x
        )
        if modes_set != 1:
            raise CliError(
                'wait: pass exactly one of --selector, --network-idle, --url-contains, '
                '--page-event, --js, --stable-ids',
                exit_code=2,
            )

        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        start = time.monotonic()

        async with open_browser(opts) as (_browser, tab):
            try:
                if selector is not None:
                    matched = await _wait_selector(tab, selector, count=count, timeout=wait)
                elif network_idle:
                    matched = await _wait_network_idle(
                        tab,
                        idle_ms=idle_ms,
                        max_inflight=max_inflight,
                        timeout=wait,
                    )
                elif url_contains is not None:
                    matched = await _wait_url_contains(tab, url_contains, timeout=wait)
                elif page_event is not None:
                    matched = await _wait_page_event(tab, page_event, timeout=wait)
                elif js is not None:
                    matched = await _wait_js(tab, js, timeout=wait)
                else:
                    assert stable_ids is not None
                    matched = await _wait_stable_ids(
                        tab,
                        stable_ids,
                        stable_ms=stable_ms,
                        timeout=wait,
                    )
            except (TimeoutError, asyncio.TimeoutError) as e:
                # Python 3.10's asyncio.TimeoutError is distinct from TimeoutError;
                # in 3.11+ they're the same. Catch both so asyncio.wait_for() and
                # our own raised TimeoutError both translate to exit 3.
                elapsed = (time.monotonic() - start) * 1000
                raise CliError(
                    f'wait timed out after {elapsed:.0f}ms: {e}',
                    exit_code=EXIT_TIMEOUT,
                ) from e

        printer.emit(
            {
                'ready': True,
                'ms': int((time.monotonic() - start) * 1000),
                'matched': matched,
            },
        )


# ---- Mode implementations --------------------------------------------------


async def _wait_selector(tab: Any, selector: str, *, count: int, timeout: float) -> dict[str, Any]:
    if count <= 1:
        element = await tab.query(selector, timeout=int(timeout), raise_exc=False)
        if element is None:
            raise TimeoutError(f'selector {selector!r} not found')
        return {'selector': selector, 'count': 1}
    # For count > 1, poll via JS — tab.query returns the first match.
    deadline = time.monotonic() + timeout
    sel_json = json.dumps(selector)
    script = f'document.querySelectorAll({sel_json}).length'
    while time.monotonic() < deadline:
        result = await tab.execute_script(script, return_by_value=True, await_promise=False)
        n = _scalar_value(result)
        if isinstance(n, int) and n >= count:
            return {'selector': selector, 'count': n}
        await asyncio.sleep(0.2)
    raise TimeoutError(f'selector {selector!r} matched < {count} elements')


async def _wait_network_idle(
    tab: Any,
    *,
    idle_ms: int,
    max_inflight: int,
    timeout: float,
) -> dict[str, Any]:
    inflight: set[str] = set()
    last_change = asyncio.get_running_loop().time()

    def _on_request(event: dict[str, Any]) -> None:
        nonlocal last_change
        rid = event.get('params', {}).get('requestId')
        if rid:
            inflight.add(rid)
            last_change = asyncio.get_running_loop().time()

    def _on_finished(event: dict[str, Any]) -> None:
        nonlocal last_change
        rid = event.get('params', {}).get('requestId')
        if rid and rid in inflight:
            inflight.discard(rid)
            last_change = asyncio.get_running_loop().time()

    network_was_enabled = getattr(tab, 'network_events_enabled', False)
    if not network_was_enabled:
        await tab.enable_network_events()
    cb_ids: list[int] = []
    try:
        cb_ids.append(await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT.value, _on_request))
        cb_ids.append(await tab.on(NetworkEvent.LOADING_FINISHED.value, _on_finished))
        cb_ids.append(await tab.on(NetworkEvent.LOADING_FAILED.value, _on_finished))

        deadline = asyncio.get_running_loop().time() + timeout
        idle_seconds = idle_ms / 1000.0
        while True:
            now = asyncio.get_running_loop().time()
            if now >= deadline:
                raise TimeoutError(
                    f'network never settled to <= {max_inflight} in-flight for {idle_ms}ms',
                )
            if len(inflight) <= max_inflight and (now - last_change) >= idle_seconds:
                return {'inflight': len(inflight), 'idle_ms': idle_ms}
            await asyncio.sleep(0.1)
    finally:
        for cb_id in cb_ids:
            with contextlib.suppress(Exception):
                await tab.remove_callback(cb_id)
        if not network_was_enabled:
            with contextlib.suppress(Exception):
                await tab.disable_network_events()


async def _wait_url_contains(tab: Any, needle: str, *, timeout: float) -> dict[str, Any]:
    current = await tab.current_url
    if needle in current:
        return {'url': current}

    page_was_enabled = getattr(tab, 'page_events_enabled', False)
    if not page_was_enabled:
        await tab.enable_page_events()
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(f'URL never contained {needle!r}')
            try:
                await wait_for_event(
                    tab,
                    PageEvent.FRAME_NAVIGATED.value,
                    timeout=remaining,
                )
            except (TimeoutError, asyncio.TimeoutError) as e:
                raise TimeoutError(f'URL never contained {needle!r}') from e
            current = await tab.current_url
            if needle in current:
                return {'url': current}
    finally:
        if not page_was_enabled:
            with contextlib.suppress(Exception):
                await tab.disable_page_events()


async def _wait_page_event(tab: Any, event_alias: str, *, timeout: float) -> dict[str, Any]:
    alias = event_alias.lower()
    event_name = _PAGE_EVENT_MAP.get(alias)
    if event_name is None:
        raise CliError(
            f'--page-event must be one of: {", ".join(_PAGE_EVENT_MAP)} (got {event_alias!r})',
            exit_code=2,
        )
    # Resolve immediately if the page is already past this milestone — the
    # CDP event has already fired and a fresh listener would hang for the
    # NEXT navigation that may never come.
    if alias in ('load', 'dom-content'):
        with contextlib.suppress(Exception):
            result = await tab.execute_script(
                'return document.readyState',
                return_by_value=True,
            )
            ready = _scalar_value(result)
            if alias == 'load' and ready == 'complete':
                return {'event': event_alias, 'already': ready}
            if alias == 'dom-content' and ready in ('interactive', 'complete'):
                return {'event': event_alias, 'already': ready}
    page_was_enabled = getattr(tab, 'page_events_enabled', False)
    if not page_was_enabled:
        await tab.enable_page_events()
    try:
        await wait_for_event(tab, event_name, timeout=timeout)
        return {'event': event_alias}
    finally:
        if not page_was_enabled:
            with contextlib.suppress(Exception):
                await tab.disable_page_events()


async def _wait_js(tab: Any, expr: str, *, timeout: float) -> dict[str, Any]:
    """Poll a JS expression server-side via a single Promise."""
    poll_ms = 200
    expr_safe = expr.rstrip(';')
    script = f"""
    new Promise((res, rej) => {{
        const start = Date.now();
        const tick = () => {{
            let v;
            try {{ v = ({expr_safe}); }} catch (e) {{ return rej(e); }}
            if (v) return res({{ok: true, value: v}});
            if (Date.now() - start >= {int(timeout * 1000)})
                return res({{ok: false, value: v}});
            setTimeout(tick, {poll_ms});
        }};
        tick();
    }})
    """
    result = await tab.execute_script(script, return_by_value=True, await_promise=True)
    payload = _scalar_value(result)
    if not isinstance(payload, dict) or not payload.get('ok'):
        raise TimeoutError(f'JS never became truthy: {expr}')
    return {'value': payload.get('value')}


async def _wait_stable_ids(
    tab: Any,
    spec: str,
    *,
    stable_ms: int,
    timeout: float,
) -> dict[str, Any]:
    if '|' not in spec:
        raise CliError(
            'wait --stable-ids expects "SELECTOR|ID_ATTR" (e.g. ".row|data-id")',
            exit_code=2,
        )
    selector, _, attr = spec.partition('|')
    if not selector or not attr:
        raise CliError(
            'wait --stable-ids: both selector and attribute are required',
            exit_code=2,
        )
    poll_ms = 200
    sel_json = json.dumps(selector)
    attr_json = json.dumps(attr)
    script = f"""
    new Promise(res => {{
        const start = Date.now();
        let lastIds = new Set();
        let stableSince = 0;
        const tick = () => {{
            const ids = new Set(
                Array.from(document.querySelectorAll({sel_json}))
                    .map(el => el.getAttribute({attr_json}))
                    .filter(Boolean)
            );
            const newIds = [...ids].filter(id => !lastIds.has(id));
            const grew = newIds.length > 0;
            if (grew) {{
                stableSince = 0;
                lastIds = ids;
            }} else if (lastIds.size > 0) {{
                if (!stableSince) stableSince = Date.now();
                if (Date.now() - stableSince >= {stable_ms})
                    return res({{ok: true, count: lastIds.size, ms: Date.now() - start}});
            }}
            if (Date.now() - start >= {int(timeout * 1000)})
                return res({{ok: false, count: lastIds.size, ms: Date.now() - start}});
            setTimeout(tick, {poll_ms});
        }};
        tick();
    }})
    """
    result = await tab.execute_script(script, return_by_value=True, await_promise=True)
    payload = _scalar_value(result)
    if not isinstance(payload, dict) or not payload.get('ok'):
        count = payload.get('count') if isinstance(payload, dict) else None
        raise TimeoutError(
            f'IDs never stabilized for {stable_ms}ms (saw {count} so far)',
        )
    return {'count': payload.get('count'), 'selector': selector, 'attr': attr}


def _scalar_value(result: Any) -> Any:
    """Drill into pydoll's execute_script return for the JS value."""
    if not isinstance(result, dict):
        return None
    inner = result.get('result', {})
    if isinstance(inner, dict) and ('result' in inner or 'exceptionDetails' in inner):
        ro = inner.get('result') or {}
    else:
        ro = inner if isinstance(inner, dict) else {}
    if isinstance(ro, dict) and 'value' in ro:
        return ro['value']
    return ro
