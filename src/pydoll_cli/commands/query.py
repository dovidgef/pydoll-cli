"""`query URL SELECTOR` — find elements and emit their data as JSON/table."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.commands._shared import _normalize_url_selector
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'query',
        help='Find element(s) by selector and print their text/attributes.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli query https://example.com "h1"\n'
            '  pydoll-cli query https://example.com "a" --all --attr href\n'
            '  pydoll-cli query https://example.com "input[name=q]" --attr value\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        url: Annotated[
            str | None, typer.Argument(help='URL (omit with --session/--connect).')
        ] = None,
        selector: Annotated[str, typer.Argument(help='CSS or XPath selector.')] = '',
        find_all: Annotated[
            bool, typer.Option('--all', help='Return all matching elements.')
        ] = False,
        attr: Annotated[
            str | None,
            typer.Option('--attr', help='Return this attribute instead of text.'),
        ] = None,
        wait: Annotated[
            int,
            typer.Option('--wait', help='Wait up to N seconds for element to appear.'),
        ] = 0,
    ) -> None:
        url, selector = _normalize_url_selector(url, selector)
        if not selector:
            raise CliError('Missing SELECTOR argument.', exit_code=2)
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)
        async with open_browser(opts) as (_browser, tab):
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            result = await tab.query(
                selector,
                timeout=wait,
                find_all=find_all,
                raise_exc=False,
            )
            if result is None:
                raise CliError(f'Selector not found: {selector!r}', exit_code=4)
            elements = result if isinstance(result, list) else [result]
            items: list[dict[str, Any]] = []
            for el in elements:
                items.append(
                    {
                        'text': (await el.text) or '',
                        'attr': el.get_attribute(attr) if attr else None,
                        'tag': el.tag_name,
                    }
                )
        if not find_all:
            payload = items[0]
            # In text mode default to attr value (or text) on a single line.
            text_line = payload['attr'] if attr else payload['text']
            printer.emit(payload, text=text_line or '')
        else:
            printer.emit(
                items, text='\n'.join((i['attr'] if attr else i['text']) or '' for i in items)
            )
