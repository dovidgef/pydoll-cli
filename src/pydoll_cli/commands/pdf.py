"""`pdf URL -o FILE` — save the page as a PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'pdf',
        help='Save the page as a PDF.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli pdf https://example.com -o page.pdf\n'
            '  pydoll-cli pdf https://example.com -o page.pdf --landscape --scale 0.8\n'
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
            typer.Option('-o', '--output-path', help='Destination PDF file.'),
        ] = None,
        landscape: Annotated[
            bool, typer.Option('--landscape', help='Landscape orientation.')
        ] = False,
        display_header_footer: Annotated[
            bool,
            typer.Option('--header-footer', help='Include default header/footer.'),
        ] = False,
        print_background: Annotated[
            bool,
            typer.Option('--background/--no-background', help='Include background graphics.'),
        ] = True,
        scale: Annotated[float, typer.Option('--scale', help='Scale factor 0.1-2.0.')] = 1.0,
        as_base64: Annotated[
            bool, typer.Option('--base64', help='Emit base64 instead of writing a file.')
        ] = False,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        if not as_base64 and output_path is None:
            raise CliError('Provide -o/--output-path or use --base64.', exit_code=2)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if as_base64:
                data = await tab.print_to_pdf(
                    as_base64=True,
                    landscape=landscape,
                    display_header_footer=display_header_footer,
                    print_background=print_background,
                    scale=scale,
                )
                printer.emit({'base64': data})
            else:
                await tab.print_to_pdf(
                    path=str(output_path),
                    landscape=landscape,
                    display_header_footer=display_header_footer,
                    print_background=print_background,
                    scale=scale,
                )
                printer.emit_path(output_path)  # type: ignore[arg-type]
