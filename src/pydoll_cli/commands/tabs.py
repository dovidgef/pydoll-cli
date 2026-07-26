"""`tabs` subcommand group — list/open/close/focus browser tabs."""

from __future__ import annotations

from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer
from pydoll_cli.targets import visible_tabs

group_app = typer.Typer(
    help='Manage browser tabs (list / new / close / focus).',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'list',
    help='List open tabs in the attached browser.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session my tabs list\n'
        '  pydoll-cli --connect ws://127.0.0.1:9222/devtools/browser/X tabs list --output json\n'
    ),
)
@run_async
async def list_tabs(ctx: typer.Context) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (browser, _tab):
        tabs = await visible_tabs(browser, include_internal=opts.include_internal)
        rows = []
        for i, t in enumerate(tabs):
            try:
                url = await t.current_url
                title = await t.title
            except Exception:
                url, title = None, None
            rows.append(
                {
                    'index': i,
                    'target_id': t._target_id,
                    'type': 'page',
                    'url': url,
                    'title': title,
                }
            )
    if opts.output == 'json':
        printer.emit(rows)
        return
    if not rows:
        printer.emit('no tabs', text='no tabs')
        return
    for r in rows:
        title = (r['title'] or '')[:60]
        url = (r['url'] or '')[:80]
        print(f'{r["index"]:>2}  {title:<60}  {url}')


@group_app.command(
    'new',
    help='Open a new tab.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session my tabs new\n'
        '  pydoll-cli --session my tabs new --url https://example.com\n'
    ),
)
@run_async
async def new_tab_cmd(
    ctx: typer.Context,
    url: Annotated[
        str | None,
        typer.Option('--url', help='Navigate the new tab to this URL on creation.'),
    ] = None,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (browser, _tab):
        new_tab = await browser.new_tab(url=url or '')
        target_id = new_tab._target_id
    printer.emit(
        {'target_id': target_id, 'url': url},
        text=f'opened tab {target_id}' + (f' → {url}' if url else ''),
    )


@group_app.command(
    'close',
    help='Close a tab by its index (see `tabs list`).',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session my tabs close 2\n'
        '  pydoll-cli --session my tabs close --target-id AAAA-BBBB\n'
    ),
)
@run_async
async def close_tab_cmd(
    ctx: typer.Context,
    index: Annotated[
        int | None,
        typer.Argument(help='Tab index from `tabs list`. Omit with --target-id.'),
    ] = None,
    target_id: Annotated[
        str | None,
        typer.Option('--target-id', help='Close by CDP target ID instead of index.'),
    ] = None,
) -> None:
    if index is None and target_id is None:
        raise CliError('Provide either INDEX or --target-id.', exit_code=2)
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (browser, _tab):
        tabs = await visible_tabs(browser, include_internal=opts.include_internal)
        chosen = None
        if target_id is not None:
            for t in tabs:
                if t._target_id == target_id:
                    chosen = t
                    break
            if chosen is None:
                raise CliError(f'No tab with target_id {target_id!r}.', exit_code=4)
        else:
            if index is None or index < 0 or index >= len(tabs):
                raise CliError(
                    f'--tab index {index} out of range (have {len(tabs)} tabs).',
                    exit_code=2,
                )
            chosen = tabs[index]
        closed_id = chosen._target_id
        await chosen.close()
    printer.emit({'closed': closed_id}, text=f'closed tab {closed_id}')


@group_app.command(
    'focus',
    help='Bring a tab to the front.',
    epilog='Examples:\n  pydoll-cli --session my tabs focus 0\n',
)
@run_async
async def focus_tab_cmd(
    ctx: typer.Context,
    index: Annotated[int, typer.Argument(help='Tab index from `tabs list`.')],
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (browser, _tab):
        tabs = await visible_tabs(browser, include_internal=opts.include_internal)
        if index < 0 or index >= len(tabs):
            raise CliError(
                f'--tab index {index} out of range (have {len(tabs)} tabs).',
                exit_code=2,
            )
        chosen = tabs[index]
        await chosen.bring_to_front()
        target_id = chosen._target_id
    printer.emit({'focused': target_id}, text=f'focused tab {target_id}')
