"""`scroll` — page or element scrolling, including infinite-scroll loops."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

import typer
from pydoll.constants import ScrollPosition

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'scroll',
        help='Scroll the page (relative, absolute, to bottom, or to a selector).',
        epilog=(
            'Examples:\n'
            '  pydoll-cli --session s scroll --by-y 800\n'
            '  pydoll-cli --session s scroll --by-y -400 --humanize\n'
            '  pydoll-cli --session s scroll --to-y 0\n'
            '  pydoll-cli --session s scroll --to-bottom --max-loops 10 --idle-ms 800\n'
            '  pydoll-cli --session s scroll --to-selector ".footer"\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        by_y: Annotated[
            int | None,
            typer.Option(
                '--by-y',
                help='Scroll by N pixels (negative = up).',
            ),
        ] = None,
        to_y: Annotated[
            int | None,
            typer.Option('--to-y', help='Scroll to absolute Y position (0 = top).'),
        ] = None,
        to_bottom: Annotated[
            bool,
            typer.Option(
                '--to-bottom',
                help='Scroll to bottom; loop on infinite-scroll pages until content stops growing.',
            ),
        ] = False,
        to_selector: Annotated[
            str | None,
            typer.Option('--to-selector', help='Scroll an element into view by selector.'),
        ] = None,
        max_loops: Annotated[
            int,
            typer.Option('--max-loops', help='With --to-bottom: max scroll iterations.'),
        ] = 10,
        idle_ms: Annotated[
            int,
            typer.Option(
                '--idle-ms',
                help='With --to-bottom: ms to wait between scrolls before checking growth.',
            ),
        ] = 800,
        humanize: Annotated[
            bool,
            typer.Option('--humanize', help='Smooth/momentum scrolling for relative + endpoints.'),
        ] = False,
    ) -> None:
        modes = sum(
            1 for x in (by_y is not None, to_y is not None, to_bottom, to_selector) if x
        )
        if modes != 1:
            raise CliError(
                'scroll: pass exactly one of --by-y, --to-y, --to-bottom, --to-selector',
                exit_code=2,
            )

        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if by_y is not None:
                position = ScrollPosition.DOWN if by_y >= 0 else ScrollPosition.UP
                await tab.scroll.by(position, abs(by_y), humanize=humanize)
                payload: dict[str, Any] = {'scrolled': {'by_y': by_y}}
            elif to_y is not None:
                # pydoll has no absolute scroll primitive — drop to JS.
                behavior = 'smooth' if humanize else 'auto'
                await tab.execute_script(
                    f'window.scrollTo({{top: {to_y}, behavior: {json.dumps(behavior)}}})',
                    return_by_value=True,
                    await_promise=False,
                )
                payload = {'scrolled': {'to_y': to_y}}
            elif to_bottom:
                payload = await _scroll_to_bottom(
                    tab, max_loops=max_loops, idle_ms=idle_ms, humanize=humanize,
                )
            else:
                assert to_selector is not None
                element = await tab.query(to_selector, timeout=5, raise_exc=False)
                if element is None:
                    raise CliError(f'Selector not found: {to_selector!r}', exit_code=4)
                await element.scroll_into_view()
                payload = {'scrolled': {'to_selector': to_selector}}
        printer.emit(payload)


async def _scroll_to_bottom(
    tab: Any, *, max_loops: int, idle_ms: int, humanize: bool,
) -> dict[str, Any]:
    last_height = -1
    loops = 0
    while loops < max_loops:
        await tab.scroll.to_bottom(humanize=humanize)
        await asyncio.sleep(idle_ms / 1000.0)
        result = await tab.execute_script(
            'document.body.scrollHeight', return_by_value=True, await_promise=False,
        )
        height = _scalar_value(result)
        loops += 1
        if isinstance(height, (int, float)) and int(height) == last_height:
            return {'scrolled': {'to_bottom': True, 'loops': loops, 'height': int(height)}}
        if isinstance(height, (int, float)):
            last_height = int(height)
    return {
        'scrolled': {
            'to_bottom': True,
            'loops': loops,
            'height': last_height,
            'stable': False,
        },
    }


def _scalar_value(result: object) -> object:
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
