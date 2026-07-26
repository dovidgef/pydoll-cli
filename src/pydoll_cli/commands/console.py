"""`console` subcommand group — read browser console output and JS errors.

Chrome buffers console history per document (1000 entries, FIFO) and replays it
to any client that enables the Runtime and Log domains — including a connection
that did not exist when the page loaded. So ``console logs`` works retroactively
on a tab that some earlier invocation navigated, with no prior arming and no
daemon on our side. History clears on navigation/reload, and replay is
non-destructive (enabling again re-delivers it).

Two sources are enabled together, because neither alone is complete:

- ``Runtime`` → ``consoleAPICalled`` (``console.log`` and friends) and
  ``exceptionThrown`` (uncaught JS errors).
- ``Log`` → ``entryAdded`` for browser-generated messages — failed requests,
  CSP violations, deprecations, mixed content — which Runtime never reports.

pydoll has no ``protocol/log`` module, so the Log domain is driven with raw
command dicts through ``tab._execute_command``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import time
from typing import Annotated, Any

import typer
from pydoll.protocol.runtime.events import RuntimeEvent

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import Printer

group_app = typer.Typer(
    help='Read browser console output and uncaught JS errors.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)

LOG_ENTRY_ADDED = 'Log.entryAdded'

# Map a console API call type onto one of the five levels. Anything not listed
# (clear, startGroup, count, …) is informational output → 'log'.
_CONSOLE_TYPE_LEVELS = {
    'debug': 'debug',
    'info': 'info',
    'warning': 'warning',
    'error': 'error',
    'assert': 'error',
}


# ---- Normalization ------------------------------------------------------


def _stringify_arg(remote_object: Any) -> str:
    """Render one CDP RemoteObject as text.

    Primitives carry ``value``; objects and functions carry only
    ``description`` or a shallow ``preview``. Without the fallback chain,
    ``console.log({a: 1})`` renders as ``None``.
    """
    if not isinstance(remote_object, dict):
        return str(remote_object)
    if 'value' in remote_object:
        value = remote_object['value']
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)
    description = remote_object.get('description')
    if description:
        return str(description)
    preview = remote_object.get('preview')
    if isinstance(preview, dict):
        described = preview.get('description')
        if described:
            return str(described)
        props = preview.get('properties')
        if isinstance(props, list):
            inner = ', '.join(f'{p.get("name")}: {p.get("value")}' for p in props)
            return f'{{{inner}}}'
    return str(remote_object.get('type', ''))


def _frames(stack_trace: Any) -> list[dict[str, Any]] | None:
    if not isinstance(stack_trace, dict):
        return None
    call_frames = stack_trace.get('callFrames')
    if not isinstance(call_frames, list) or not call_frames:
        return None
    return [
        {
            'function': f.get('functionName') or None,
            'url': f.get('url') or None,
            'line': f.get('lineNumber'),
            'column': f.get('columnNumber'),
        }
        for f in call_frames
        if isinstance(f, dict)
    ]


def _record(
    *,
    source: str,
    level: str,
    type_: str,
    text: str,
    url: str | None = None,
    line: int | None = None,
    column: int | None = None,
    timestamp: float | None = None,
    stack: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The one normalized shape every event type collapses into."""
    return {
        'source': source,
        'level': level,
        'type': type_,
        'text': text,
        'url': url,
        'line': line,
        'column': column,
        'timestamp': timestamp,
        'stack': stack,
    }


def _normalize(event: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """Turn one raw CDP event into a normalized record, or None to drop it.

    ``kind`` is one of ``console-api``, ``exception``, ``log-entry`` — which
    of the three subscriptions delivered this event.
    """
    params = event.get('params', {}) or {}

    if kind == 'console-api':
        call_type = str(params.get('type') or 'log')
        args = params.get('args') or []
        text = ' '.join(_stringify_arg(a) for a in args)
        stack = _frames(params.get('stackTrace'))
        top = stack[0] if stack else {}
        return _record(
            source='console-api',
            level=_CONSOLE_TYPE_LEVELS.get(call_type, 'log'),
            type_=call_type,
            text=text,
            url=top.get('url'),
            line=top.get('line'),
            column=top.get('column'),
            timestamp=params.get('timestamp'),
            stack=stack,
        )

    if kind == 'exception':
        details = params.get('exceptionDetails', {}) or {}
        exception = details.get('exception', {}) or {}
        text = str(
            exception.get('description') or details.get('text') or exception.get('value') or ''
        )
        return _record(
            source='exception',
            level='error',
            type_='exception',
            text=text,
            url=details.get('url'),
            line=details.get('lineNumber'),
            column=details.get('columnNumber'),
            timestamp=params.get('timestamp'),
            stack=_frames(details.get('stackTrace')),
        )

    entry = params.get('entry', {}) or {}
    entry_source = str(entry.get('source') or 'other')
    if entry_source == 'console-api':
        # Some Chrome versions mirror console calls into the Log domain.
        # Runtime already covers those; keeping both would double every line.
        return None
    return _record(
        source=entry_source,
        level=str(entry.get('level') or 'log'),
        type_='entry',
        text=str(entry.get('text') or ''),
        url=entry.get('url'),
        line=entry.get('lineNumber'),
        column=None,
        timestamp=entry.get('timestamp'),
        stack=_frames(entry.get('stackTrace')),
    )


# ---- Filtering ----------------------------------------------------------


def _csv_set(raw: str | None) -> set[str] | None:
    """Parse a comma list into a lowercase set; None means 'no narrowing'."""
    if raw is None:
        return None
    values = {part.strip().lower() for part in raw.split(',') if part.strip()}
    return values or None


def _matches(
    rec: dict[str, Any],
    *,
    levels: set[str] | None,
    kinds: set[str] | None,
    substring: str | None,
) -> bool:
    if levels is not None and str(rec.get('level', '')).lower() not in levels:
        return False
    if kinds is not None and str(rec.get('source', '')).lower() not in kinds:
        return False
    return not (substring is not None and substring not in str(rec.get('text', '')))


def _sort_key(rec: dict[str, Any]) -> float:
    ts = rec.get('timestamp')
    return float(ts) if isinstance(ts, (int, float)) else 0.0


def _text_line(rec: dict[str, Any]) -> str:
    location = ''
    if rec.get('url'):
        location = f'  ({rec["url"]}'
        if rec.get('line') is not None:
            location += f':{rec["line"]}'
        location += ')'
    return f'{rec["level"]!s:<7} {rec["source"]!s:<12} {rec["text"]}{location}'


# ---- CDP plumbing -------------------------------------------------------


async def _enable_sources(tab: Any) -> None:
    """Enable Runtime and Log. Both replay this document's buffered history."""
    await tab.enable_runtime_events()
    await tab._execute_command({'method': 'Log.enable', 'params': {}})


async def _disable_sources(tab: Any) -> None:
    with contextlib.suppress(Exception):
        await tab._execute_command({'method': 'Log.disable', 'params': {}})
    with contextlib.suppress(Exception):
        await tab.disable_runtime_events()


async def _clear_history(tab: Any) -> None:
    """Empty both replay buffers so the next read doesn't re-deliver these."""
    with contextlib.suppress(Exception):
        await tab._execute_command({'method': 'Runtime.discardConsoleEntries', 'params': {}})
    with contextlib.suppress(Exception):
        await tab._execute_command({'method': 'Log.clear', 'params': {}})


async def _subscribe(tab: Any, handler: Any) -> list[int]:
    """Register ``handler(event, kind)`` against all three event types."""
    cb_ids: list[int] = []
    for event_name, kind in (
        (RuntimeEvent.CONSOLE_API_CALLED.value, 'console-api'),
        (RuntimeEvent.EXCEPTION_THROWN.value, 'exception'),
        (LOG_ENTRY_ADDED, 'log-entry'),
    ):

        def _make(kind: str = kind) -> Any:
            def _cb(event: dict[str, Any]) -> None:
                handler(event, kind)

            return _cb

        cb_ids.append(await tab.on(event_name, _make()))
    return cb_ids


async def _unsubscribe(tab: Any, cb_ids: list[int]) -> None:
    for cb_id in cb_ids:
        with contextlib.suppress(Exception):
            await tab.remove_callback(cb_id)


# ---- Commands -----------------------------------------------------------


@group_app.command(
    'logs',
    help=(
        "Dump the current document's buffered console history and exit. "
        'Works retroactively — no prior arming needed.'
    ),
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s console logs\n'
        '  pydoll-cli --session s console logs --level error,warning\n'
        '  pydoll-cli --session s console logs --filter "hydrat" --output json\n'
    ),
)
@run_async
async def logs(
    ctx: typer.Context,
    level: Annotated[
        str | None,
        typer.Option(
            '--level',
            help='Comma list of levels to keep: log,debug,info,warning,error. Default: all.',
        ),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option(
            '--kind',
            help=(
                'Comma list matched against the record source: console-api, exception, '
                'network, security, deprecation, … Default: all.'
            ),
        ),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring filter on the message text.'),
    ] = None,
    settle: Annotated[
        float,
        typer.Option(
            '--settle',
            help='Stop after this many seconds with no new message (capped by --timeout).',
        ),
    ] = 0.3,
    duration: Annotated[
        float | None,
        typer.Option(
            '--duration',
            help='Collect for a fixed number of seconds instead of settling. '
            'Use when you also want to catch messages emitted while this runs.',
        ),
    ] = None,
    clear: Annotated[
        bool,
        typer.Option(
            '--clear',
            help="Discard the browser's console history after draining, so a "
            'later `console logs` returns only what is new.',
        ),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    levels, kinds = _csv_set(level), _csv_set(kind)

    records: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    last_seen = [loop.time()]

    def _on_event(event: dict[str, Any], kind_name: str) -> None:
        rec = _normalize(event, kind_name)
        last_seen[0] = loop.time()
        if rec is not None:
            records.append(rec)

    async with open_browser(opts) as (_browser, tab):
        # Subscribe *before* enabling: the replay burst starts the moment the
        # domain is enabled, and a callback registered after it would miss it.
        cb_ids: list[int] = []
        try:
            cb_ids = await _subscribe(tab, _on_event)
            await _enable_sources(tab)
            last_seen[0] = loop.time()
            deadline = loop.time() + opts.timeout
            if duration is not None and duration > 0:
                await asyncio.sleep(min(duration, max(0.0, deadline - loop.time())))
            else:
                # Replay lands immediately, so a fixed window would just be dead
                # wait. Finish once the burst goes quiet.
                while True:
                    now = loop.time()
                    quiet_left = settle - (now - last_seen[0])
                    time_left = deadline - now
                    if quiet_left <= 0 or time_left <= 0:
                        break
                    await asyncio.sleep(min(quiet_left, time_left))
            if clear:
                await _clear_history(tab)
        finally:
            await _unsubscribe(tab, cb_ids)
            await _disable_sources(tab)

    out = sorted(
        (r for r in records if _matches(r, levels=levels, kinds=kinds, substring=filter)),
        key=_sort_key,
    )
    if opts.output == 'json':
        printer.emit(out)
        return
    printer.emit(out, text='\n'.join(_text_line(r) for r in out))


@group_app.command(
    'watch',
    help='Stream console messages as NDJSON to stdout. Runs until SIGINT or --max-events.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s console watch | head\n'
        '  pydoll-cli --session s console watch --level error --max-events 10\n'
        '  pydoll-cli --session s console watch --no-replay\n'
    ),
)
@run_async
async def watch(
    ctx: typer.Context,
    max_events: Annotated[
        int,
        typer.Option('--max-events', help='Stop after this many messages (0 = unlimited).'),
    ] = 0,
    level: Annotated[
        str | None,
        typer.Option('--level', help='Comma list of levels to keep. Default: all.'),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option('--kind', help='Comma list matched against the record source. Default: all.'),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring filter on the message text.'),
    ] = None,
    replay: Annotated[
        bool,
        typer.Option(
            '--replay/--no-replay',
            help=(
                "Enabling the domains replays this document's history first, which is "
                'usually useful context. --no-replay starts from now.'
            ),
        ),
    ] = True,
) -> None:
    opts: GlobalOptions = ctx.obj
    levels, kinds = _csv_set(level), _csv_set(kind)
    counter = [0]
    done = asyncio.Event()
    # CDP timestamps are ms since epoch, so this is directly comparable.
    started_ms = time.time() * 1000

    def _emit(rec: dict[str, Any]) -> None:
        if max_events and counter[0] >= max_events:
            return
        json.dump(rec, sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        sys.stdout.flush()
        counter[0] += 1
        if max_events and counter[0] >= max_events:
            done.set()

    def _on_event(event: dict[str, Any], kind_name: str) -> None:
        rec = _normalize(event, kind_name)
        if rec is None:
            return
        if not replay and _sort_key(rec) < started_ms:
            return
        if not _matches(rec, levels=levels, kinds=kinds, substring=filter):
            return
        _emit(rec)

    async with open_browser(opts) as (_browser, tab):
        # Subscribe before enabling so the replay burst isn't missed.
        cb_ids: list[int] = []
        try:
            cb_ids = await _subscribe(tab, _on_event)
            await _enable_sources(tab)
            await done.wait()
        finally:
            await _unsubscribe(tab, cb_ids)
            await _disable_sources(tab)
