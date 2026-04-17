"""`cookies` subcommand group — list/set/clear cookies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

group_app = typer.Typer(
    help='Read/write cookies.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'get',
    help='Get cookies for the current tab (or the whole browser context).',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session my cookies get\n'
        '  pydoll-cli --session my cookies get --domain example.com\n'
    ),
)
@run_async
async def get_cookies(
    ctx: typer.Context,
    domain: Annotated[
        str | None,
        typer.Option('--domain', help='Filter to cookies matching this domain substring.'),
    ] = None,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        cookies = await tab.get_cookies()
    if domain:
        cookies = [c for c in cookies if domain in c.get('domain', '')]
    printer.emit(cookies)


@group_app.command(
    'set',
    help='Set cookies from a JSON file (list of CookieParam dicts).',
    epilog=('Examples:\n  pydoll-cli --session my cookies set --file cookies.json\n'),
)
@run_async
async def set_cookies(
    ctx: typer.Context,
    file: Annotated[Path, typer.Option('--file', help='Path to JSON file.')] = Path('cookies.json'),
) -> None:
    if not file.exists():
        raise CliError(f'File not found: {file}', exit_code=2)
    data = json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(data, list):
        raise CliError('Cookies JSON must be a list of objects.', exit_code=2)
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.set_cookies(data)
    printer.emit({'set': len(data)}, text=f'set {len(data)} cookies')


@group_app.command('clear', help='Delete all cookies for the current context.')
@run_async
async def clear_cookies(ctx: typer.Context) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.delete_all_cookies()
    printer.emit({'cleared': True}, text='cookies cleared')
