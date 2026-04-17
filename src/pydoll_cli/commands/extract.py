"""`extract URL --schema FILE` — structured extraction via a Pydantic model."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.extractor_loader import load as load_schema
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'extract',
        help='Run pydoll structured extraction against a Pydantic/JSON schema.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli extract https://quotes.toscrape.com --schema quote.json\n'
            '  pydoll-cli extract https://quotes.toscrape.com \\\n'
            '      --schema quote.json --scope ".quote" --all\n'
            '  pydoll-cli extract https://site.com --schema models.py --schema-class Article\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        schema: Annotated[
            Path | None,
            typer.Option(
                '--schema', help='Path to schema.py (ExtractionModel subclass) or schema.json.'
            ),
        ] = None,
        schema_class: Annotated[
            str | None,
            typer.Option('--schema-class', help='Class name inside the .py schema.'),
        ] = None,
        scope: Annotated[
            str | None,
            typer.Option('--scope', help='CSS scope selector when using --all.'),
        ] = None,
        extract_all: Annotated[
            bool,
            typer.Option('--all', help='Return a list of extracted records.'),
        ] = False,
    ) -> None:
        if schema is None:
            raise CliError('--schema is required.', exit_code=2)
        if not schema.exists():
            raise CliError(f'Schema file not found: {schema}', exit_code=2)
        model_cls = load_schema(schema, schema_class)

        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if extract_all:
                if not scope:
                    raise CliError('--scope is required with --all.', exit_code=2)
                items = await tab.extract_all(model_cls, scope=scope, timeout=int(opts.timeout))
                data = [i.model_dump() for i in items]
            else:
                item = await tab.extract(model_cls, timeout=int(opts.timeout))
                data = item.model_dump()
        printer.emit(data)
