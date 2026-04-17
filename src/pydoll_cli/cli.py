"""Top-level typer application — global options and subcommand wiring.

Global options are collected in the root callback and stored on the typer
`Context.obj` as a `GlobalOptions` dataclass instance. Every subcommand
receives the full `GlobalOptions` via `ctx.obj`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli import __version__
from pydoll_cli.commands import browsers as browsers_cmd
from pydoll_cli.commands import (
    bundle as bundle_cmd,
)
from pydoll_cli.commands import (
    click as click_cmd,
)
from pydoll_cli.commands import (
    cloudflare as cloudflare_cmd,
)
from pydoll_cli.commands import (
    cookies as cookies_cmd,
)
from pydoll_cli.commands import (
    eval_ as eval_cmd,
)
from pydoll_cli.commands import (
    extract as extract_cmd,
)
from pydoll_cli.commands import (
    har as har_cmd,
)
from pydoll_cli.commands import (
    info as info_cmd,
)
from pydoll_cli.commands import (
    navigate as navigate_cmd,
)
from pydoll_cli.commands import (
    network as network_cmd,
)
from pydoll_cli.commands import (
    pdf as pdf_cmd,
)
from pydoll_cli.commands import (
    query as query_cmd,
)
from pydoll_cli.commands import (
    request as request_cmd,
)
from pydoll_cli.commands import (
    run as run_cmd,
)
from pydoll_cli.commands import (
    screenshot as screenshot_cmd,
)
from pydoll_cli.commands import (
    session as session_cmd,
)
from pydoll_cli.commands import (
    shell as shell_cmd,
)
from pydoll_cli.commands import (
    source as source_cmd,
)
from pydoll_cli.commands import (
    tabs as tabs_cmd,
)
from pydoll_cli.commands import (
    text as text_cmd,
)
from pydoll_cli.commands import (
    type_ as type_cmd,
)
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import configure_logging

app = typer.Typer(
    name='pydoll-cli',
    no_args_is_help=True,
    add_completion=True,
    rich_markup_mode='rich',
    help=(
        'pydoll-cli — automate Chromium browsers (Chrome, Edge, Wavebox, Chromium) '
        'via the Chrome DevTools Protocol. Wraps the [bold]pydoll[/] library.\n\n'
        'Use [cyan]pydoll-cli <command> --help[/] for details and examples.'
    ),
    epilog=(
        'Examples:\n'
        '  pydoll-cli screenshot https://example.com -o shot.png\n'
        '  pydoll-cli --output json get https://example.com\n'
        '  pydoll-cli session start agent-run --no-headless\n'
        '  pydoll-cli --session agent-run query "a.storylink" --all --attr href\n'
    ),
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f'pydoll-cli {__version__}')
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            '--version',
            help='Show pydoll-cli version and exit.',
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    browser: Annotated[
        str,
        typer.Option(
            '--browser',
            help='Which browser to drive.',
            case_sensitive=False,
            show_default=True,
        ),
    ] = 'chrome',
    browser_binary: Annotated[
        Path | None,
        typer.Option(
            '--browser-binary',
            help='Full path to the browser executable. Overrides --browser detection.',
            exists=False,
        ),
    ] = None,
    headless: Annotated[
        bool,
        typer.Option('--headless/--no-headless', help='Run browser headless.'),
    ] = True,
    user_data_dir: Annotated[
        Path | None,
        typer.Option('--user-data-dir', help='Persistent profile directory.'),
    ] = None,
    incognito: Annotated[bool, typer.Option('--incognito', help='Launch incognito.')] = False,
    proxy: Annotated[
        str | None,
        typer.Option('--proxy', help='Proxy URL, scheme://user:pass@host:port.'),
    ] = None,
    user_agent: Annotated[
        str | None,
        typer.Option('--user-agent', help='Override User-Agent (Client Hints auto-synced).'),
    ] = None,
    accept_languages: Annotated[
        str | None,
        typer.Option('--accept-languages', help='Accept-Language list, e.g. en-US,en.'),
    ] = None,
    window_size: Annotated[
        str | None,
        typer.Option('--window-size', help='Window size WxH, e.g. 1920x1080.'),
    ] = None,
    disable_images: Annotated[
        bool,
        typer.Option('--disable-images', help='Skip image loading for speed.'),
    ] = False,
    extra_args: Annotated[
        list[str] | None,
        typer.Option('-a', '--arg', help='Raw Chromium flag, repeatable.'),
    ] = None,
    prefs: Annotated[
        list[str] | None,
        typer.Option('--pref', help='Dotted browser preference KEY=VALUE, repeatable.'),
    ] = None,
    cdp_port: Annotated[
        int | None,
        typer.Option('--cdp-port', help='Fix the CDP remote-debugging port.'),
    ] = None,
    connect: Annotated[
        str | None,
        typer.Option('--connect', help='Attach to a running browser via ws:// URL.'),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option('--session', help='Reuse a persistent session by name.'),
    ] = None,
    tab: Annotated[
        int | None,
        typer.Option('--tab', help='Target a specific tab index (with --session/--connect).'),
    ] = None,
    tab_url: Annotated[
        str | None,
        typer.Option('--tab-url', help='Target the tab whose URL contains this substring.'),
    ] = None,
    new_tab: Annotated[
        bool,
        typer.Option(
            '--new-tab',
            help='With --connect/--session: open a new tab in the default context.',
        ),
    ] = False,
    fresh: Annotated[
        bool,
        typer.Option(
            '--fresh',
            help=(
                'With --connect/--session: open a new incognito browser context and a fresh '
                'tab within it, leaving the existing tabs untouched. Useful to drive an '
                'already-logged-in browser without disturbing the user.'
            ),
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option('--timeout', help='Per-command timeout in seconds.'),
    ] = 30.0,
    output: Annotated[
        str,
        typer.Option('--output', help='Output format.', case_sensitive=False),
    ] = 'text',
    quiet: Annotated[bool, typer.Option('-q', '--quiet', help='Suppress non-data output.')] = False,
    log_level: Annotated[
        str,
        typer.Option('--log-level', help='Python logging level (forwarded to pydoll).'),
    ] = 'WARNING',
    log_file: Annotated[
        Path | None,
        typer.Option('--log-file', help='Write pydoll logs to this file.'),
    ] = None,
) -> None:
    """pydoll-cli — automate Chromium browsers via CDP."""
    browser_lc = browser.lower()
    if browser_lc not in ('chrome', 'edge', 'wavebox', 'chromium'):
        raise typer.BadParameter(
            f'--browser must be one of: chrome, edge, wavebox, chromium (got {browser!r})',
        )
    output_lc = output.lower()
    if output_lc not in ('text', 'json'):
        raise typer.BadParameter(f'--output must be "text" or "json" (got {output!r})')

    opts = GlobalOptions(
        browser=browser_lc,  # type: ignore[arg-type]
        browser_binary=browser_binary,
        headless=headless,
        user_data_dir=user_data_dir,
        incognito=incognito,
        proxy=proxy,
        user_agent=user_agent,
        accept_languages=accept_languages,
        window_size=window_size,
        disable_images=disable_images,
        extra_args=list(extra_args or []),
        prefs=list(prefs or []),
        cdp_port=cdp_port,
        connect=connect,
        session=session,
        tab=tab,
        tab_url=tab_url,
        new_tab=new_tab,
        fresh=fresh,
        timeout=timeout,
        output=output_lc,  # type: ignore[arg-type]
        quiet=quiet,
        log_level=log_level,
        log_file=log_file,
    )
    configure_logging(opts)
    ctx.obj = opts


# ---- Register subcommands ------------------------------------------------

# Groups (add as sub-typers)
app.add_typer(session_cmd.group_app, name='session')
app.add_typer(cookies_cmd.group_app, name='cookies')
app.add_typer(har_cmd.group_app, name='har')
app.add_typer(network_cmd.group_app, name='network')
app.add_typer(cloudflare_cmd.group_app, name='cloudflare')
app.add_typer(tabs_cmd.group_app, name='tabs')

# Flat commands
navigate_cmd.register(app)
screenshot_cmd.register(app)
pdf_cmd.register(app)
bundle_cmd.register(app)
source_cmd.register(app)
text_cmd.register(app)
eval_cmd.register(app)
query_cmd.register(app)
click_cmd.register(app)
type_cmd.register(app)
extract_cmd.register(app)
request_cmd.register(app)
shell_cmd.register(app)
run_cmd.register(app)
info_cmd.register(app)
browsers_cmd.register(app)
