"""`get URL` — navigate to a URL and print title/URL."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'get',
        help='Navigate to URL and print title.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli get https://example.com\n'
            '  pydoll-cli --output json get https://example.com\n'
            '  pydoll-cli get https://app.com --wait-for ".content" --wait 30\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[str, typer.Argument(help='URL to load.')],
        wait: Annotated[
            float | None,
            typer.Option(
                '--wait',
                help=(
                    'When --wait-for is set: seconds to poll for that selector. '
                    'Otherwise: extra seconds to sleep after load.'
                ),
            ),
        ] = None,
        wait_for: Annotated[
            str | None,
            typer.Option(
                '--wait-for',
                help=(
                    'CSS or XPath selector to wait for after navigation. '
                    'Exits 4 if the element never appears within --wait seconds '
                    '(default 30).'
                ),
            ),
        ] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            await tab.go_to(url, timeout=int(opts.timeout))
            if wait_for:
                timeout = wait if wait is not None else 30.0
                element = await tab.query(wait_for, timeout=int(timeout), raise_exc=False)
                if element is None:
                    raise CliError(
                        f'--wait-for selector not found within {timeout:g}s: {wait_for!r}',
                        exit_code=4,
                    )
            elif wait:
                await asyncio.sleep(wait)
            title = await tab.title
            current = await tab.current_url
        payload: dict[str, object] = {'url': current, 'title': title}
        if wait_for:
            payload['wait_for'] = wait_for
        printer.emit(payload)
