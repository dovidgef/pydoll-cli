"""`network` subcommand group — dump or stream captured network activity."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from typing import Annotated, Any

import typer
from pydoll.protocol.network.events import NetworkEvent

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


@group_app.command(
    'watch',
    help='Stream network events as NDJSON to stdout. Runs until SIGINT or --max-events.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network watch | head\n'
        '  pydoll-cli --session s network watch --max-events 50 --kind response\n'
        '  pydoll-cli --session s network watch --filter "/api/" --kind both\n'
    ),
)
@run_async
async def watch(
    ctx: typer.Context,
    max_events: Annotated[
        int,
        typer.Option('--max-events', help='Stop after this many events (0 = unlimited).'),
    ] = 0,
    kind: Annotated[
        str,
        typer.Option(
            '--kind',
            help='Which events to stream: request | response | both.',
            case_sensitive=False,
        ),
    ] = 'request',
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring URL filter (request URL or response URL).'),
    ] = None,
) -> None:
    kind_lc = kind.lower()
    if kind_lc not in ('request', 'response', 'both'):
        raise typer.BadParameter(f'--kind must be request | response | both (got {kind!r})')

    opts: GlobalOptions = ctx.obj
    counter = [0]
    done = asyncio.Event()

    def _emit(rec: dict[str, Any]) -> None:
        json.dump(rec, sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        sys.stdout.flush()
        counter[0] += 1
        if max_events and counter[0] >= max_events:
            done.set()

    def _on_request(event: dict[str, Any]) -> None:
        url = event.get('params', {}).get('request', {}).get('url', '')
        if filter and filter not in url:
            return
        _emit(
            {
                'kind': 'request',
                'request_id': event['params'].get('requestId'),
                'url': url,
                'method': event['params'].get('request', {}).get('method'),
                'headers': event['params'].get('request', {}).get('headers'),
                'type': event['params'].get('type'),
                'timestamp': event['params'].get('timestamp'),
            },
        )

    def _on_response(event: dict[str, Any]) -> None:
        resp = event.get('params', {}).get('response', {})
        url = resp.get('url', '')
        if filter and filter not in url:
            return
        _emit(
            {
                'kind': 'response',
                'request_id': event['params'].get('requestId'),
                'url': url,
                'status': resp.get('status'),
                'mime_type': resp.get('mimeType'),
                'headers': resp.get('headers'),
                'timestamp': event['params'].get('timestamp'),
            },
        )

    async with open_browser(opts) as (_browser, tab):
        await tab.enable_network_events()
        cb_ids: list[int] = []
        try:
            if kind_lc in ('request', 'both'):
                cb_ids.append(
                    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT.value, _on_request),
                )
            if kind_lc in ('response', 'both'):
                cb_ids.append(
                    await tab.on(NetworkEvent.RESPONSE_RECEIVED.value, _on_response),
                )
            await done.wait()
        finally:
            for cb_id in cb_ids:
                with contextlib.suppress(Exception):
                    await tab.remove_callback(cb_id)
            with contextlib.suppress(Exception):
                await tab.disable_network_events()
