"""`browsers` — list browsers detected on this system."""

from __future__ import annotations

import typer

from pydoll_cli import browsers as browsers_mod
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'browsers',
        help='List Chromium-based browsers detected on this system.',
        epilog='Examples:\n  pydoll-cli browsers\n  pydoll-cli --output json browsers\n',
    )
    def _cmd(ctx: typer.Context) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        candidates = browsers_mod.detect_all()
        data = [
            {'kind': c.kind, 'display_name': c.display_name, 'path': str(c.path)}
            for c in candidates
        ]
        if opts.output == 'json':
            printer.emit(data)
            return
        if not data:
            printer.emit('no browsers detected', text='no browsers detected')
            return
        for row in data:
            print(f'{row["kind"]:<10} {row["display_name"]:<18} {row["path"]}')
