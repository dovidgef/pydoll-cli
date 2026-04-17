"""`click URL SELECTOR` — click an element."""

from __future__ import annotations

from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.commands._shared import _normalize_url_selector
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'click',
        help='Find an element and click it (with humanized mouse movement).',
        epilog=(
            'Examples:\n'
            '  pydoll-cli click https://example.com "a.more"\n'
            '  pydoll-cli click https://example.com "button" --wait 5\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        selector: Annotated[str, typer.Argument(help='CSS or XPath selector.')] = '',
        wait: Annotated[int, typer.Option('--wait', help='Seconds to wait for element.')] = 5,
        human: Annotated[bool, typer.Option('--human/--fast', help='Humanized click.')] = True,
    ) -> None:
        url, selector = _normalize_url_selector(url, selector)
        if not selector:
            raise CliError('Missing SELECTOR argument.', exit_code=2)
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            element = await tab.query(selector, timeout=wait, raise_exc=False)
            if element is None:
                raise CliError(f'Selector not found: {selector!r}', exit_code=4)
            await element.click() if human else await element.click_using_js()
            after_url = await tab.current_url
        printer.emit({'clicked': selector, 'url': after_url})
