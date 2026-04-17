"""`shell` — interactive async REPL with `browser` and `tab` pre-bound."""

from __future__ import annotations

import asyncio
import code
from typing import Annotated, Any

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'shell',
        help='Interactive Python REPL with `browser` and `tab` already bound.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli shell https://example.com\n'
            '  pydoll-cli --session my shell\n'
            '\n'
            'Inside the shell, use `await expr` to run coroutines directly\n'
            '(asyncio PyREPL mode; `tab.take_screenshot(...)` etc. all work).\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[str | None, typer.Argument(help='Optional URL to load.')] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            printer.info('entering async shell; use `await expr` for coroutines. Ctrl-D to exit.')
            banner = (
                f'pydoll-cli shell — browser={opts.browser!r}, '
                f'{"session=" + opts.session if opts.session else "fresh launch"}'
            )
            _run_async_repl(
                locals_={'browser': browser, 'tab': tab, 'asyncio': asyncio}, banner=banner
            )


def _run_async_repl(locals_: dict[str, Any], banner: str) -> None:
    """Drop into an interactive async REPL. Uses PyREPL when available."""
    try:
        import asyncio.__main__ as async_repl  # noqa: PLC0415

        async_repl.banner = banner
        async_repl.repl(locals=locals_)
        return
    except (ImportError, AttributeError):
        pass
    code.interact(banner=banner, local=locals_)
