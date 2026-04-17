"""`eval URL --script '...' | --file PATH | -` — run JavaScript and return the result."""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'eval',
        help='Execute JavaScript in the page context and return the result.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli eval https://example.com --script "return document.title"\n'
            '  pydoll-cli eval https://example.com --file probe.js\n'
            '  echo "return navigator.userAgent" | pydoll-cli eval https://example.com -\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        script_input: Annotated[
            str | None,
            typer.Argument(help='Pass "-" to read JS from stdin.'),
        ] = None,
        script: Annotated[
            str | None,
            typer.Option('--script', help='Inline JavaScript source.'),
        ] = None,
        file: Annotated[
            Path | None,
            typer.Option('--file', help='Path to a .js file.'),
        ] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)

        # Resolve script source.
        src: str | None = None
        if script is not None:
            src = script
        elif file is not None:
            src = file.read_text(encoding='utf-8')
        elif script_input == '-':
            src = sys.stdin.read()
        if src is None or not src.strip():
            raise CliError(
                'Provide a script via --script, --file, or "-" (stdin).',
                exit_code=2,
            )

        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            result = await tab.execute_script(src)
        value = result.get('result', {}).get('result', {}).get('value')
        if opts.output == 'json':
            printer.emit({'value': value})
        elif isinstance(value, (dict, list)):
            printer.emit(value, text=_json.dumps(value, indent=2, ensure_ascii=False))
        else:
            printer.emit(value, text='' if value is None else str(value))
