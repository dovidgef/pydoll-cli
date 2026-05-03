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
    help='Register a session — launch a new browser or attach to a running one.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli session start agent-run\n'
        '  pydoll-cli session start research --no-headless --url https://example.com\n'
        '  # Attach to an already-running Chrome/Wavebox on port 9222, in an isolated\n'
        '  # incognito context (default for Wavebox; opt-in for others). Note: --browser\n'
        '  # is a GLOBAL option and must come before the `session` subcommand:\n'
        '  pydoll-cli --browser wavebox session start agent-run\n'
        '  pydoll-cli session start agent-run --attach\n'
        "  # Pin a tab in the user's logged-in profile (shares cookies):\n"
        '  pydoll-cli --browser wavebox session start work --share-profile --url https://...\n'
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
    attach: Annotated[
        bool,
        typer.Option(
            '--attach/--no-attach',
            help=(
                'Attach to a running browser instead of launching a new one, and '
                'create an isolated incognito context + tab. Default: true for '
                'Wavebox (whose app-level onboarding blocks fresh launches), false '
                'for Chrome/Edge/Chromium.'
            ),
        ),
    ] = False,
    attach_port: Annotated[
        int,
        typer.Option('--attach-port', help='CDP port of the running browser to attach to.'),
    ] = 9222,
    share_profile: Annotated[
        bool,
        typer.Option(
            '--share-profile',
            help=(
                "With --attach: open the pinned tab in the running browser's default "
                'context (shares cookies/logins with your real session) instead of a '
                'fresh incognito context. `session stop` then closes only the tab.'
            ),
        ),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)

    # Default policy: Wavebox can't cleanly fresh-launch, so attach by default.
    use_attach = attach or opts.browser == 'wavebox'

    try:
        if use_attach:
            ws = await session_mod.probe_running_browser([attach_port])
            if ws is None:
                raise CliError(
                    f'No running browser found on CDP port {attach_port}. '
                    f'Start your {opts.browser.capitalize()} with --remote-debugging-port='
                    f'{attach_port} and try again, or pass --no-attach to launch one.',
                    exit_code=5,
                )
            state = await session_mod.start_attached(
                name,
                ws,
                opts,
                initial_url=url,
                use_incognito=not share_profile,
            )
        else:
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
    if state.attached:
        mode = 'shared-profile' if state.browser_context_id is None else 'incognito'
        text = f'attached session {name!r} ({mode}) on port {state.port}'
    else:
        text = f'started session {name!r} on port {state.port} (pid {state.pid})'
    printer.emit(data, text=text)


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
            kind = 'attached' if r.get('attached') else 'owned   '
            print(f'{r["name"]:<20} {kind}  port={r["port"]:<5} pid={r["pid"]:<7} {status}')


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
