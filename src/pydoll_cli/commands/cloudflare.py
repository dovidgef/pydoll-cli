"""`cloudflare` subcommand group — bypass Cloudflare Turnstile."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer

group_app = typer.Typer(
    help='Cloudflare Turnstile captcha bypass.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'bypass',
    help='Navigate to URL, bypass Turnstile if present, emit resulting HTML or screenshot.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli cloudflare bypass https://example-protected.com\n'
        '  pydoll-cli cloudflare bypass https://example-protected.com -o page.html\n'
        '  pydoll-cli cloudflare bypass https://example-protected.com --screenshot shot.png\n'
    ),
)
@run_async
async def bypass(
    ctx: typer.Context,
    url: Annotated[str, typer.Argument(help='URL behind a Cloudflare Turnstile challenge.')],
    output_path: Annotated[
        Path | None,
        typer.Option('-o', '--output-path', help='Write resulting HTML to this file.'),
    ] = None,
    screenshot: Annotated[
        Path | None,
        typer.Option('--screenshot', help='Also save a screenshot to this path.'),
    ] = None,
    wait_after: Annotated[
        float,
        typer.Option('--wait-after', help='Extra seconds to wait after bypass.'),
    ] = 2.0,
    captcha_timeout: Annotated[
        float,
        typer.Option(
            '--captcha-timeout',
            help=(
                'Seconds to wait for the Turnstile widget to appear before giving up '
                '(maps to pydoll time_to_wait_captcha; default 5). Increase if the '
                'bypass returns but the page is still on the challenge.'
            ),
        ),
    ] = 5.0,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        async with tab.expect_and_bypass_cloudflare_captcha(
            time_to_wait_captcha=captcha_timeout,
        ):
            await tab.go_to(url, timeout=int(opts.timeout))
        if wait_after > 0:
            await asyncio.sleep(wait_after)
        html = await tab.page_source
        if screenshot is not None:
            await tab.take_screenshot(path=str(screenshot))
    result: dict[str, object] = {'url': url, 'bytes': len(html.encode('utf-8'))}
    if output_path is not None:
        output_path.write_text(html, encoding='utf-8')
        result['path'] = str(output_path)
    if screenshot is not None:
        result['screenshot'] = str(screenshot)
    if output_path is None and opts.output != 'json':
        # Stream HTML to stdout when user didn't pick a file.
        print(html)
    else:
        printer.emit(result)
