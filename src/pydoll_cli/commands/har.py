"""`har` subcommand group — HAR recording/replay."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

group_app = typer.Typer(
    help='Record and replay HAR files.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'record',
    help='Record network activity for a URL and save as HAR.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli har record https://example.com -o flow.har\n'
        '  pydoll-cli har record https://example.com -o flow.har --duration 10\n'
    ),
)
@run_async
async def record(
    ctx: typer.Context,
    url: Annotated[str | None, typer.Argument(help='URL (omit with --session/--connect).')] = None,
    output_path: Annotated[
        Path,
        typer.Option('-o', '--output-path', help='Destination .har file.'),
    ] = Path('flow.har'),
    duration: Annotated[
        float,
        typer.Option('--duration', help='Seconds to keep recording after navigation.'),
    ] = 0.0,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        async with tab.request.record() as capture:
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if duration > 0:
                await asyncio.sleep(duration)
        capture.save(output_path)
        count = len(capture.entries)
    printer.emit(
        {'path': str(output_path), 'entries': count}, text=f'{count} entries → {output_path}'
    )


@group_app.command(
    'replay',
    help='Replay requests from a HAR file against the current session.',
    epilog=('Examples:\n  pydoll-cli --session my har replay flow.har\n'),
)
@run_async
async def replay(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help='HAR file to replay.')],
) -> None:
    if not file.exists():
        raise CliError(f'HAR file not found: {file}', exit_code=2)
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        responses = await tab.request.replay(str(file))
    summary = [{'status': r.status_code, 'url': getattr(r, 'url', None)} for r in responses]
    printer.emit(
        {'replayed': len(summary), 'responses': summary}, text=f'replayed {len(summary)} requests'
    )
