"""`request METHOD URL` — issue an HTTP call via the browser's fetch API."""

from __future__ import annotations

import json as _json
from typing import Annotated

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer


def register(app: typer.Typer) -> None:
    @app.command(
        'request',
        help="Hybrid HTTP via the browser's fetch API (inherits cookies/auth).",
        epilog=(
            'Examples:\n'
            '  pydoll-cli request GET https://httpbin.org/get\n'
            '  pydoll-cli --session logged-in request GET https://my-site.com/api/me\n'
            '  pydoll-cli request POST https://api.example.com/x --json \'{"k":1}\'\n'
        ),
    )
    @run_async
    async def _cmd(
        ctx: typer.Context,
        method: Annotated[str, typer.Argument(help='GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS.')],
        url: Annotated[str, typer.Argument(help='Target URL.')],
        data: Annotated[
            str | None,
            typer.Option('--data', help='Form-encoded body (key=value&key=value).'),
        ] = None,
        json_body: Annotated[
            str | None,
            typer.Option('--json', help='JSON body (a JSON literal string).'),
        ] = None,
        headers: Annotated[
            list[str] | None,
            typer.Option('-H', '--header', help='Additional header, repeatable: "Name: value".'),
        ] = None,
    ) -> None:
        opts: GlobalOptions = ctx.obj
        printer = Printer(opts)

        m = method.upper()
        if m not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'):
            raise CliError(f'Unsupported method {method!r}', exit_code=2)

        header_entries = []
        for h in headers or []:
            if ':' not in h:
                raise CliError(f'Bad header {h!r}; expected "Name: value".', exit_code=2)
            name, _, value = h.partition(':')
            header_entries.append({'name': name.strip(), 'value': value.strip()})

        body_json = None
        body_data = data
        if json_body is not None:
            try:
                body_json = _json.loads(json_body)
            except _json.JSONDecodeError as e:
                raise CliError(f'--json is not valid JSON: {e}', exit_code=2) from e

        async with open_browser(opts) as (_browser, tab):
            response = await tab.request.request(
                m,
                url,
                data=body_data,
                json=body_json,
                headers=header_entries,
            )

        try:
            payload = response.json()
        except Exception:
            payload = None
        out = {
            'status': response.status_code,
            'url': url,
            'headers': dict(response.headers or {}),
            'json': payload,
            'text': None if payload is not None else response.text,
        }
        printer.emit(out)
