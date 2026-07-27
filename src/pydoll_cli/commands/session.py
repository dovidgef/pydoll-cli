"""`session` subcommand group — manage persistent detached browsers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

import typer

from pydoll_cli import session as session_mod
from pydoll_cli.async_runner import run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer, human_bytes

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
        typer.Option(
            '--url',
            help=(
                'Navigate to this URL on startup. With --share-profile, if a '
                'tab matching this URL is already open, it is adopted as-is '
                '(no re-navigation) instead of duplicating it.'
            ),
        ),
    ] = None,
    tab_url: Annotated[
        str | None,
        typer.Option(
            '--tab-url',
            help=(
                'Adopt-only: pin an already-open tab whose URL contains this '
                'substring. Errors if no match. Requires --share-profile. '
                'session stop leaves the adopted tab open by default.'
            ),
        ),
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

    if tab_url is not None:
        if not share_profile:
            raise CliError(
                '--tab-url requires --share-profile (incognito tabs are not part '
                "of the user's visible profile to adopt).",
                exit_code=2,
            )
        if url is not None:
            raise CliError(
                '--tab-url and --url are mutually exclusive. Use --url for '
                'create-or-reuse, --tab-url for adopt-only.',
                exit_code=2,
            )
        if not use_attach:
            raise CliError('--tab-url requires --attach.', exit_code=2)

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
                tab_url=tab_url,
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


@group_app.command('stop', help='Stop a session, remove its state, and delete its profile.')
def stop(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help='Session name.')],
    timeout: Annotated[
        float, typer.Option('--timeout', help='Seconds to wait for graceful exit.')
    ] = 10.0,
    close_tab: Annotated[
        bool,
        typer.Option(
            '--close-tab',
            help=(
                'Shared-profile mode only: also close the pinned tab. Default '
                "is to leave it open (since adopted user tabs shouldn't be "
                'taken down).'
            ),
        ),
    ] = False,
    purge: Annotated[
        bool,
        typer.Option(
            '--purge/--no-purge',
            help=(
                "Delete the session's on-disk profile dir (default). Use "
                '--no-purge to keep it so a later `session start NAME` reuses '
                'the same profile (e.g. to preserve a login); a kept profile is '
                'protected from `session prune`.'
            ),
        ),
    ] = True,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    try:
        session_mod.stop(name, timeout=timeout, close_tab=close_tab)
    except FileNotFoundError as e:
        raise CliError(str(e), exit_code=6) from e
    if purge:
        freed = session_mod.purge_profile(name)
    else:
        # Record the intent, so `prune` can tell a deliberately retained
        # profile apart from one that was simply abandoned.
        freed = 0
        session_mod.mark_kept(name)
    text = f'stopped session {name!r}'
    if freed:
        text += f' (freed {human_bytes(freed)})'
    printer.emit({'stopped': name, 'reclaimed_bytes': freed, 'kept_profile': not purge}, text=text)


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
    # Surface leftover profile dirs that have no state file so they're visible
    # and can be reclaimed with `session prune`/`session rm`. Profiles kept on
    # purpose by `stop --no-purge` are listed as `kept`, not `orphan`, since
    # `prune` deliberately leaves them alone.
    orphan_paths = session_mod.orphan_dirs(include_kept=True)
    if opts.output == 'json':
        orphans = [
            {
                'name': p.name,
                'orphan': not session_mod.is_kept(p.name),
                'kept': session_mod.is_kept(p.name),
                'path': str(p),
                'size_bytes': session_mod.dir_size(p),
            }
            for p in orphan_paths
        ]
        printer.emit(rows + orphans)
    else:
        if not rows and not orphan_paths:
            printer.info('no sessions')
            return
        for r in rows:
            status = 'alive' if r['alive'] else 'dead'
            kind = 'attached' if r.get('attached') else 'owned   '
            print(f'{r["name"]:<20} {kind}  port={r["port"]:<5} pid={r["pid"]:<7} {status}')
        for p in orphan_paths:
            size = human_bytes(session_mod.dir_size(p))
            kind = 'kept  ' if session_mod.is_kept(p.name) else 'orphan'
            print(f'{p.name:<20} {kind}    {size:<10} {p}')


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


@group_app.command(
    'prune',
    help='Reclaim disk space by deleting leftover session profiles.',
    epilog=(
        'Requires at least one selector (--orphans/--dead/--older-than).\n'
        'Never touches a live session, and never a profile kept by '
        '`stop --no-purge` unless you pass --include-kept.\n\n'
        'Examples:\n'
        '  pydoll-cli session prune --orphans --dry-run\n'
        '  pydoll-cli session prune --orphans --yes\n'
        '  pydoll-cli session prune --dead --older-than 7 --yes\n'
    ),
)
@run_async
async def prune(
    ctx: typer.Context,
    orphans: Annotated[
        bool,
        typer.Option('--orphans', help='Profile dirs with no matching state file.'),
    ] = False,
    dead: Annotated[
        bool,
        typer.Option('--dead', help='Registered sessions whose browser is not alive.'),
    ] = False,
    older_than: Annotated[
        float | None,
        typer.Option(
            '--older-than',
            help=(
                'Only profiles older than N days. Filters --orphans/--dead; used '
                'alone, selects any non-alive profile older than N days.'
            ),
        ),
    ] = None,
    include_kept: Annotated[
        bool,
        typer.Option(
            '--include-kept',
            help=(
                'Also reclaim profiles that `stop --no-purge` kept on purpose. '
                'They are protected by default — that is the point of --no-purge.'
            ),
        ),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option('--dry-run', help='Report what would be deleted without deleting.'),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option('--yes', '-y', help='Skip the confirmation prompt.'),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    if not (orphans or dead or older_than is not None):
        # No selector: nothing is safe to delete by default — show usage.
        typer.echo(ctx.get_help())
        raise typer.Exit()

    candidates = await session_mod.collect_prune_candidates(
        orphans=orphans, dead=dead, older_than_days=older_than, include_kept=include_kept
    )
    total = sum(c.size for c in candidates)
    payload = {
        'candidates': [
            {'name': c.name, 'reason': c.reason, 'size_bytes': c.size, 'path': str(c.path)}
            for c in candidates
        ],
        'count': len(candidates),
        'reclaimed_bytes': total,
    }

    if not candidates:
        printer.emit({**payload, 'pruned': False}, text='nothing to prune')
        return

    if dry_run:
        lines = [f'{c.name:<20} {c.reason:<7} {human_bytes(c.size)}' for c in candidates]
        lines.append(f'would reclaim {human_bytes(total)} from {len(candidates)} profile(s)')
        printer.emit({**payload, 'dry_run': True}, text='\n'.join(lines))
        return

    if not yes:
        if opts.output == 'json':
            raise CliError('refusing to prune without --yes in json mode', exit_code=2)
        if not typer.confirm(f'Delete {len(candidates)} profile(s) ({human_bytes(total)})?'):
            raise typer.Exit(1)

    for c in candidates:
        session_mod.purge_profile(c.name)
        session_mod.state_path(c.name).unlink(missing_ok=True)
    printer.emit(
        {**payload, 'pruned': True},
        text=f'pruned {len(candidates)} profile(s), reclaimed {human_bytes(total)}',
    )


@group_app.command('rm', help='Stop session(s) if running and delete their profiles entirely.')
@run_async
async def rm(
    ctx: typer.Context,
    names: Annotated[list[str], typer.Argument(help='Session name(s) to remove.')],
    timeout: Annotated[
        float, typer.Option('--timeout', help='Seconds to wait for graceful exit.')
    ] = 10.0,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    removed: list[str] = []
    total = 0
    for name in names:
        try:
            total += await session_mod.remove_async(name, timeout=timeout)
        except FileNotFoundError as e:
            raise CliError(str(e), exit_code=6) from e
        removed.append(name)
    printer.emit(
        {'removed': removed, 'reclaimed_bytes': total},
        text=f'removed {len(removed)} session(s), reclaimed {human_bytes(total)}',
    )
