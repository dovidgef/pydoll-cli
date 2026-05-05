"""`upload SELECTOR FILE [FILE...]` — set files on a file input or via the chooser dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'upload',
        help='Set files on an <input type="file">, or open a file chooser via a button click.',
        epilog=(
            'Examples:\n'
            "  pydoll-cli --session s upload 'input[type=file]' /path/to/a.png\n"
            "  pydoll-cli --session s upload '#avatar' /a.jpg /b.jpg\n"
            '  # Hidden input behind a styled button: --via-chooser then SELECTOR is the BUTTON\n'
            "  pydoll-cli --session s upload '.upload-button' /a.png --via-chooser\n"
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        selector: Annotated[
            str,
            typer.Argument(
                help='File input selector; with --via-chooser, the BUTTON that opens the chooser.',
            ),
        ],
        files: Annotated[
            list[Path],
            typer.Argument(help='One or more existing file paths.'),
        ],
        via_chooser: Annotated[
            bool,
            typer.Option(
                '--via-chooser',
                help=(
                    'Click SELECTOR inside an expect_file_chooser() context. Use when the '
                    'real <input> is hidden and a styled button opens it.'
                ),
            ),
        ] = False,
        wait: Annotated[
            int,
            typer.Option('--wait', help='Seconds to poll for the element.'),
        ] = 5,
    ) -> None:
        if not files:
            raise CliError('upload: at least one FILE is required.', exit_code=2)
        for f in files:
            if not f.exists():
                raise CliError(f'upload: file does not exist: {f}', exit_code=2)
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if via_chooser:
                element = await tab.query(selector, timeout=wait, raise_exc=False)
                if element is None:
                    raise CliError(f'Selector not found: {selector!r}', exit_code=4)
                async with tab.expect_file_chooser(files=[str(f) for f in files]):
                    await element.click()
            else:
                element = await tab.query(selector, timeout=wait, raise_exc=False)
                if element is None:
                    raise CliError(f'Selector not found: {selector!r}', exit_code=4)
                await element.set_input_files([str(f) for f in files])
        printer.emit(
            {
                'selector': selector,
                'files': [str(f) for f in files],
                'via_chooser': via_chooser,
            },
        )
