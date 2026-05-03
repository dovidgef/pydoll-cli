"""`network` subcommand group — dump captured network activity."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer

group_app = typer.Typer(
    help='Network monitoring helpers.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'logs',
    help='Enable network events on the current tab and dump captured requests.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli network logs https://example.com --duration 5\n'
        '  pydoll-cli --session my network logs --filter ".js"\n'
    ),
)
@run_async
async def logs(
    ctx: typer.Context,
    url: Annotated[
        str | None, typer.Argument(help='Optional URL to navigate before collecting.')
    ] = None,
    duration: Annotated[
        float,
        typer.Option('--duration', help='Seconds to keep collecting after navigation.'),
    ] = 3.0,
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring filter on request URL.'),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            '--full/--slim',
            help=(
                'Slim emits {url,method,request_id} per record (default). '
                'Full emits the entire CDP event params dict (type, headers, '
                'timestamps, initiator, etc.).'
            ),
        ),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.enable_network_events()
        try:
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if duration > 0:
                await asyncio.sleep(duration)
            events = await tab.get_network_logs(filter=filter)
        finally:
            await tab.disable_network_events()
    if full:
        out = [e.get('params', {}) for e in events]
    else:
        out = [
            {
                'url': e['params'].get('request', {}).get('url'),
                'method': e['params'].get('request', {}).get('method'),
                'request_id': e['params'].get('requestId'),
            }
            for e in events
        ]
    printer.emit(out)
