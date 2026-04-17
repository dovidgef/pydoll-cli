"""`bundle URL -o FILE.zip` — save page + assets as a zip bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'bundle',
        help='Save the page + all assets as a .zip bundle for offline viewing.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli bundle https://example.com -o page.zip\n'
            '  pydoll-cli bundle https://example.com -o single.zip --inline\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        output_path: Annotated[
            Path,
            typer.Option('-o', '--output-path', help='Destination .zip file.'),
        ] = Path('page.zip'),
        inline: Annotated[
            bool,
            typer.Option('--inline', help='Inline all assets into index.html (single file).'),
        ] = False,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            await tab.save_bundle(output_path, inline_assets=inline)
            printer.emit_path(output_path)
