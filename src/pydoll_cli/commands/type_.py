"""`type URL SELECTOR TEXT` — fill an input field."""

from __future__ import annotations

from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.commands._shared import _normalize_url_selector_text
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'type',
        help='Type text into an input field.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli type https://example.com "input[name=q]" "pydoll"\n'
            '  pydoll-cli type https://example.com "#search" "hello" --human\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        selector: Annotated[str, typer.Argument(help='CSS or XPath selector.')] = '',
        text: Annotated[str, typer.Argument(help='Text to type.')] = '',
        human: Annotated[
            bool,
            typer.Option('--human/--fast', help='Human-like keystroke timing.'),
        ] = False,
        delay_ms: Annotated[
            int,
            typer.Option('--delay-ms', help='Min delay between keystrokes when --human.'),
        ] = 50,
        wait: Annotated[int, typer.Option('--wait', help='Seconds to wait for element.')] = 5,
    ) -> None:
        url, selector, text = _normalize_url_selector_text(url, selector, text)
        if not selector or not text:
            raise CliError('Both SELECTOR and TEXT are required.', exit_code=2)
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            element = await tab.query(selector, timeout=wait, raise_exc=False)
            if element is None:
                raise CliError(f'Selector not found: {selector!r}', exit_code=4)
            if human:
                await element.type_text(text, interval=delay_ms / 1000.0)
            else:
                await element.insert_text(text)
        printer.emit({'selector': selector, 'typed': text})
