"""`session` subcommand group — manage persistent detached browsers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

import typer

from pydoll_cli import session as session_mod
from pydoll_cli.async_runner import run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

group_app = typer.Typer(
    help='Manage persistent browser sessions.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'start',
    help='Launch a detached browser and register it under NAME.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli session start agent-run\n'
        '  pydoll-cli session start research --no-headless --url https://example.com\n'
    ),
)
@run_async
async def start(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help='Session name (alphanumeric/dash).')],
    url: Annotated[
        str | None,
        typer.Option('--url', help='Navigate to this URL on startup.'),
    ] = None,
    startup_timeout: Annotated[
        float,
        typer.Option('--startup-timeout', help='Seconds to wait for CDP to become ready.'),
    ] = 30.0,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    try:
        state = await session_mod.start(
            name,
            opts,
            initial_url=url,
            startup_timeout=startup_timeout,
        )
    except TimeoutError as e:
        raise CliError(str(e), exit_code=5) from e
    except FileNotFoundError as e:
        raise CliError(str(e), exit_code=5) from e
    data = asdict(state)
    printer.emit(data, text=f'started session {name!r} on port {state.port} (pid {state.pid})')


@group_app.command('stop', help='Stop a session and remove its state file.')
def stop(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help='Session name.')],
    timeout: Annotated[
        float, typer.Option('--timeout', help='Seconds to wait for graceful exit.')
    ] = 10.0,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    try:
        session_mod.stop(name, timeout=timeout)
    except FileNotFoundError as e:
        raise CliError(str(e), exit_code=6) from e
    printer.emit({'stopped': name}, text=f'stopped session {name!r}')


@group_app.command('list', help='List registered sessions and their status.')
@run_async
async def list_sessions(ctx: typer.Context) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    states = session_mod.list_states()
    rows = []
    for state in states:
        is_alive = await session_mod.alive(state)
        rows.append(
            {
                **asdict(state),
                'alive': is_alive,
            }
        )
    if opts.output == 'json':
        printer.emit(rows)
    else:
        if not rows:
            printer.info('no sessions')
            return
        for r in rows:
            status = 'alive' if r['alive'] else 'dead'
            print(f'{r["name"]:<20} port={r["port"]} pid={r["pid"]}  {status}')


@group_app.command('info', help='Show detail for a single session.')
@run_async
async def info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help='Session name.')],
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    try:
        state = session_mod.load(name)
    except FileNotFoundError as e:
        raise CliError(str(e), exit_code=6) from e
    data = asdict(state)
    data['alive'] = await session_mod.alive(state)
    printer.emit(data)


@group_app.command('attach', help="Print the browser's WebSocket URL for external tools.")
def attach(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help='Session name.')],
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    try:
        state = session_mod.load(name)
    except FileNotFoundError as e:
        raise CliError(str(e), exit_code=6) from e
    printer.emit({'ws_url': state.ws_url, 'port': state.port}, text=state.ws_url)
