"""`eval URL --script '...' | --file PATH | -` — run JavaScript and return the result."""

from __future__ import annotations

import json as _json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import EXIT_JS_ERROR, CliError, Printer


def _extract_eval_result(result: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Pull (RemoteObject, exceptionDetails) out of pydoll's execute_script return.

    Tolerates two observed shapes:
        {'result': {'result': RemoteObject, 'exceptionDetails': ...}}  # CDP-wrapped
        {'result': RemoteObject, 'exceptionDetails': ...}              # unwrapped
    """
    if not isinstance(result, dict):
        return {}, None
    inner = result.get('result', {})
    if isinstance(inner, dict) and ('result' in inner or 'exceptionDetails' in inner):
        ro = inner.get('result') or {}
        ex = inner.get('exceptionDetails')
    else:
        ro = inner if isinstance(inner, dict) else {}
        ex = result.get('exceptionDetails')
    if not isinstance(ro, dict):
        ro = {}
    if ex is not None and not isinstance(ex, dict):
        ex = None
    return ro, ex


def _js_error_message(ro: dict[str, Any], ex: dict[str, Any] | None) -> str:
    if ex is not None:
        exception = ex.get('exception')
        if isinstance(exception, dict):
            desc = exception.get('description') or exception.get('value')
            if desc:
                return str(desc)
        text = ex.get('text')
        if text:
            return str(text)
    desc = ro.get('description') or ro.get('className')
    return str(desc) if desc else 'JavaScript exception'


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
        by_value: Annotated[
            bool,
            typer.Option(
                '--by-value/--as-ref',
                help=(
                    'Return the result serialized by value (default) so dicts/lists come '
                    'back as real Python objects. Use --as-ref to keep an object reference.'
                ),
            ),
        ] = True,
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
            # await_promise=True so `eval` resolves Promises returned from JS
            # (verified to exist in pydoll-python >=2.22).
            result = await tab.execute_script(
                src,
                return_by_value=by_value,
                await_promise=True,
            )
        ro, ex = _extract_eval_result(result)
        if ex is not None or ro.get('subtype') == 'error':
            raise CliError(f'JS error: {_js_error_message(ro, ex)}', exit_code=EXIT_JS_ERROR)
        value = ro.get('value') if 'value' in ro else ro
        if opts.output == 'json':
            printer.emit({'value': value})
        elif isinstance(value, (dict, list)):
            printer.emit(value, text=_json.dumps(value, indent=2, ensure_ascii=False))
        else:
            printer.emit(value, text='' if value is None else str(value))
