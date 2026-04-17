"""`screenshot URL -o FILE` — capture a screenshot."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'screenshot',
        help='Capture a page or element screenshot.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli screenshot https://example.com -o shot.png\n'
            '  pydoll-cli screenshot https://example.com --full-page -o full.png\n'
            '  pydoll-cli screenshot https://example.com --selector "#hero" -o hero.png\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL to load, or omit with --session/--connect.')
        ] = None,
        output_path: Annotated[
            Path | None,
            typer.Option('-o', '--output-path', help='Destination file (png/jpeg/webp).'),
        ] = None,
        selector: Annotated[
            str | None,
            typer.Option('--selector', help='CSS/XPath selector for element-only screenshot.'),
        ] = None,
        full_page: Annotated[
            bool,
            typer.Option('--full-page', help='Capture beyond viewport (whole document).'),
        ] = False,
        quality: Annotated[
            int,
            typer.Option('--quality', help='Image quality 1-100 (jpeg/webp).'),
        ] = 100,
        as_base64: Annotated[
            bool,
            typer.Option('--base64', help='Return base64 to stdout instead of writing a file.'),
        ] = False,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        if not as_base64 and output_path is None:
            raise CliError('Provide -o/--output-path or use --base64.', exit_code=2)

        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if selector:
                element = await tab.query(selector, timeout=int(opts.timeout))
                if as_base64:
                    data = await element.take_screenshot(as_base64=True)
                    printer.emit({'base64': data})
                else:
                    await element.take_screenshot(path=str(output_path), quality=quality)
                    printer.emit_path(output_path)  # type: ignore[arg-type]
                return
            if as_base64:
                data = await tab.take_screenshot(
                    as_base64=True,
                    beyond_viewport=full_page,
                    quality=quality,
                )
                printer.emit({'base64': data})
            else:
                await tab.take_screenshot(
                    path=str(output_path),
                    beyond_viewport=full_page,
                    quality=quality,
                )
                printer.emit_path(output_path)  # type: ignore[arg-type]
