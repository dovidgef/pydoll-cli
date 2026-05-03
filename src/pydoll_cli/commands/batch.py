"""`batch URL [URL...]` — drive many tabs in parallel via asyncio.gather.

This is pydoll's native concurrent-tab pattern surfaced as one CLI invocation.
Useful for "screenshot these 50 URLs" or "extract h1 from each of these pages"
without paying per-URL Chrome startup cost.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Annotated, Any

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer

_DEFAULT_CONCURRENCY_CAP = 10


def register(app: typer.Typer) -> None:
    @app.command(
        'batch',
        help='Visit many URLs in parallel tabs; collect screenshots / source / a query per URL.',
        epilog=(
            'Examples:\n'
            '  pydoll-cli batch https://a.com https://b.com --query "h1"\n'
            '  pydoll-cli batch https://a.com https://b.com --screenshot-dir shots/\n'
            '  pydoll-cli batch https://a.com https://b.com --source-dir html/ --concurrency 4\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        urls: Annotated[
            list[str],
            typer.Argument(help='URLs to visit. One tab per URL, run in parallel.'),
        ],
        screenshot_dir: Annotated[
            Path | None,
            typer.Option(
                '--screenshot-dir',
                help='Save one PNG per URL to this directory (created if absent).',
            ),
        ] = None,
        source_dir: Annotated[
            Path | None,
            typer.Option(
                '--source-dir',
                help='Save the rendered HTML per URL to this directory (created if absent).',
            ),
        ] = None,
        query: Annotated[
            str | None,
            typer.Option('--query', help='Optional selector to extract from each page.'),
        ] = None,
        concurrency: Annotated[
            int | None,
            typer.Option(
                '--concurrency',
                help=f'Max tabs in flight at once (default: min(len(URLS), {_DEFAULT_CONCURRENCY_CAP})).',
            ),
        ] = None,
        wait: Annotated[
            int,
            typer.Option('--wait', help='Per-URL --query polling timeout (seconds).'),
        ] = 5,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)

        if screenshot_dir is not None:
            screenshot_dir.mkdir(parents=True, exist_ok=True)
        if source_dir is not None:
            source_dir.mkdir(parents=True, exist_ok=True)

        max_concurrent = concurrency or min(len(urls), _DEFAULT_CONCURRENCY_CAP)
        max_concurrent = max(1, max_concurrent)
        sem = asyncio.Semaphore(max_concurrent)

        async with open_browser(opts) as (browser, _default_tab):
            async def _one(idx: int, url: str) -> dict[str, Any]:
                async with sem:
                    record: dict[str, Any] = {'url': url}
                    tab = None
                    try:
                        tab = await browser.new_tab(url=url)
                        await tab.go_to(url, timeout=int(opts.timeout))
                        record['title'] = await tab.title
                        if screenshot_dir is not None:
                            shot_path = screenshot_dir / f'{idx:04d}.png'
                            await tab.take_screenshot(path=str(shot_path))
                            record['screenshot'] = str(shot_path)
                        if source_dir is not None:
                            src_path = source_dir / f'{idx:04d}.html'
                            html = await tab.page_source
                            src_path.write_text(html, encoding='utf-8')
                            record['source'] = str(src_path)
                        if query is not None:
                            element = await tab.query(query, timeout=wait, raise_exc=False)
                            if element is None:
                                record['query_result'] = None
                            else:
                                record['query_result'] = await element.text
                        record['error'] = None
                    except Exception as e:
                        record['error'] = f'{type(e).__name__}: {e}'
                    finally:
                        if tab is not None:
                            with contextlib.suppress(Exception):
                                await tab.close()
                    return record

            results = await asyncio.gather(
                *[_one(i, u) for i, u in enumerate(urls)],
            )
        printer.emit(results)
