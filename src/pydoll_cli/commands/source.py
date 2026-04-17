"""`source URL` — dump the page HTML."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'source',
        help='Print the current page source (outerHTML).',
        epilog=(
            'Examples:\n'
            '  pydoll-cli source https://example.com\n'
            '  pydoll-cli source https://example.com -o page.html\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option('-o', '--output-path', help='Write to file instead of stdout.'),
        ] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            html = await tab.page_source
        if output_path is not None:
            output_path.write_text(html, encoding='utf-8')
            printer.emit_path(output_path, extra={'bytes': len(html.encode('utf-8'))})
        elif opts.output == 'json':
            printer.emit({'html': html, 'bytes': len(html.encode('utf-8'))})
        else:
            printer.emit(html, text=html)
