"""`get URL` — navigate to a URL and print title/URL."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'get',
        help='Navigate to URL and print title.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli get https://example.com\n'
            '  pydoll-cli --output json get https://example.com\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[str, typer.Argument(help='URL to load.')],
        wait: Annotated[
            float | None,
            typer.Option('--wait', help='Additional seconds to wait after load.'),
        ] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            await tab.go_to(url, timeout=int(opts.timeout))
            if wait:
                await asyncio.sleep(wait)
            title = await tab.title
            current = await tab.current_url
            printer.emit({'url': current, 'title': title})
