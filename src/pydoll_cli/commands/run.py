"""`run SCRIPT.py` — execute a user async script with `browser` and `tab` injected."""

from __future__ import annotations

import inspect
import runpy
import sys
from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'run',
        help='Execute a user Python script with `browser` and `tab` globals.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli run scrape.py\n'
            '  pydoll-cli --session my run scrape.py --extra arg1 arg2\n'
            '\n'
            'The script can define `async def main(tab, browser): ...` which\n'
            'will be awaited if present; otherwise the top-level module body\n'
            'is executed with `browser` and `tab` bound in globals.\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        script: Annotated[Path, typer.Argument(help='Path to a .py script.')],
        extra: Annotated[
            list[str] | None,
            typer.Option('--extra', help='Extra argv to pass into the script (repeatable).'),
        ] = None,
    ) -> None:
        if not script.exists():
            raise CliError(f'Script not found: {script}', exit_code=2)
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)

        saved_argv = sys.argv
        sys.argv = [str(script), *(extra or [])]
        try:
            async with open_browser(opts) as (browser, tab):
                # Execute module in its own namespace, with browser/tab available.
                init_globals = {'browser': browser, 'tab': tab}
                ns = runpy.run_path(str(script), init_globals=init_globals, run_name='__main__')
                main = ns.get('main')
                if callable(main):
                    if inspect.iscoroutinefunction(main):
                        result = await main(tab, browser)
                    else:
                        result = main(tab, browser)
                    if result is not None:
                        printer.emit(result)
        finally:
            sys.argv = saved_argv
