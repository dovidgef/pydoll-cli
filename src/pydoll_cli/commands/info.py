"""`info` — pydoll-cli version, pydoll version, and browser information."""

from __future__ import annotations

from importlib import metadata

import typer

from pydoll_cli import __version__
from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'info',
        help='Show pydoll-cli / pydoll / browser version information.',
        epilog='Examples:\n  pydoll-cli info\n  pydoll-cli --browser edge info\n',
    )
    @run_async
    async def _cmd(ctx: typer.Context) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        try:
            pydoll_version = metadata.version('pydoll-python')
        except metadata.PackageNotFoundError:
            pydoll_version = 'unknown'
        browser_info: dict[str, object] = {}
        try:
            async with open_browser(opts) as (browser, _tab):
                info = await browser.get_version()
                browser_info = {
                    'product': info.get('product'),
                    'user_agent': info.get('userAgent'),
                    'revision': info.get('revision'),
                    'js_version': info.get('jsVersion'),
                    'protocol_version': info.get('protocolVersion'),
                }
        except Exception as e:
            browser_info = {'error': str(e)}
        data = {
            'pydoll_cli': __version__,
            'pydoll_python': pydoll_version,
            'browser': browser_info,
        }
        printer.emit(data)
