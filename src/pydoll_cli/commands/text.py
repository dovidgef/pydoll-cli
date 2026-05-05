"""`text URL [--selector CSS]` — extract visible text."""

from __future__ import annotations

from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'text',
        help='Extract visible text from the page or a specific element.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli text https://example.com\n'
            '  pydoll-cli text https://example.com --selector "h1"\n'
            '  pydoll-cli text --selector ".title" --all\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        selector: Annotated[
            str | None,
            typer.Option('--selector', help='CSS/XPath selector; default: whole body.'),
        ] = None,
        all_matches: Annotated[
            bool,
            typer.Option(
                '--all',
                help='With --selector, return text for every match as a list. Default: first match.',
            ),
        ] = False,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        if all_matches and not selector:
            raise CliError('--all requires --selector', exit_code=2)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if selector and all_matches:
                elements = await tab.query(
                    selector,
                    timeout=int(opts.timeout),
                    find_all=True,
                    raise_exc=False,
                )
                if not elements:
                    raise CliError(f'Selector not found: {selector!r}', exit_code=4)
                texts = [await el.text for el in elements]
                if opts.output == 'json':
                    printer.emit({'texts': texts, 'count': len(texts)})
                else:
                    joined = '\n'.join(texts)
                    printer.emit(joined, text=joined)
                return
            if selector:
                element = await tab.query(selector, timeout=int(opts.timeout), raise_exc=False)
                if element is None:
                    raise CliError(f'Selector not found: {selector!r}', exit_code=4)
                text = await element.text
            else:
                result = await tab.execute_script('return document.body.innerText')
                text = result['result']['result']['value']
        if opts.output == 'json':
            printer.emit({'text': text})
        else:
            printer.emit(text, text=text)
