"""`network` subcommand group — dump, stream, or intercept network activity."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from pydoll.protocol.fetch.events import FetchEvent
from pydoll.protocol.network.events import NetworkEvent
from pydoll.protocol.network.types import ErrorReason, ResourceType

from pydoll_cli.async_runner import open_browser, run_async
from pydoll_cli.context import GlobalOptions
from pydoll_cli.output import CliError, Printer

group_app = typer.Typer(
    help='Network monitoring helpers.',
    no_args_is_help=True,
    rich_markup_mode='rich',
)


@group_app.command(
    'logs',
    help='Enable network events on the current tab and dump captured requests.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli network logs https://example.com --duration 5\n'
        '  pydoll-cli --session my network logs --filter ".js"\n'
    ),
)
@run_async
async def logs(
    ctx: typer.Context,
    url: Annotated[
        str | None, typer.Argument(help='Optional URL to navigate before collecting.')
    ] = None,
    duration: Annotated[
        float,
        typer.Option('--duration', help='Seconds to keep collecting after navigation.'),
    ] = 3.0,
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring filter on request URL.'),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            '--full/--slim',
            help=(
                'Slim emits {url,method,request_id} per record (default). '
                'Full emits the entire CDP event params dict (type, headers, '
                'timestamps, initiator, etc.).'
            ),
        ),
    ] = False,
) -> None:
    opts: GlobalOptions = ctx.obj
    printer = Printer(opts)
    async with open_browser(opts) as (_browser, tab):
        await tab.enable_network_events()
        try:
            if url is not None:
                await tab.go_to(url, timeout=int(opts.timeout))
            if duration > 0:
                await asyncio.sleep(duration)
            events = await tab.get_network_logs(filter=filter)
        finally:
            await tab.disable_network_events()
    if full:
        out = [e.get('params', {}) for e in events]
    else:
        out = [
            {
                'url': e['params'].get('request', {}).get('url'),
                'method': e['params'].get('request', {}).get('method'),
                'request_id': e['params'].get('requestId'),
            }
            for e in events
        ]
    printer.emit(out)


@group_app.command(
    'watch',
    help='Stream network events as NDJSON to stdout. Runs until SIGINT or --max-events.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network watch | head\n'
        '  pydoll-cli --session s network watch --max-events 50 --kind response\n'
        '  pydoll-cli --session s network watch --filter "/api/" --kind both\n'
    ),
)
@run_async
async def watch(
    ctx: typer.Context,
    max_events: Annotated[
        int,
        typer.Option('--max-events', help='Stop after this many events (0 = unlimited).'),
    ] = 0,
    kind: Annotated[
        str,
        typer.Option(
            '--kind',
            help='Which events to stream: request | response | both.',
            case_sensitive=False,
        ),
    ] = 'request',
    filter: Annotated[
        str | None,
        typer.Option('--filter', help='Substring URL filter (request URL or response URL).'),
    ] = None,
) -> None:
    kind_lc = kind.lower()
    if kind_lc not in ('request', 'response', 'both'):
        raise typer.BadParameter(f'--kind must be request | response | both (got {kind!r})')

    opts: GlobalOptions = ctx.obj
    counter = [0]
    done = asyncio.Event()

    def _emit(rec: dict[str, Any]) -> None:
        if max_events and counter[0] >= max_events:
            return
        json.dump(rec, sys.stdout, ensure_ascii=False)
        sys.stdout.write('\n')
        sys.stdout.flush()
        counter[0] += 1
        if max_events and counter[0] >= max_events:
            done.set()

    def _on_request(event: dict[str, Any]) -> None:
        url = event.get('params', {}).get('request', {}).get('url', '')
        if filter and filter not in url:
            return
        _emit(
            {
                'kind': 'request',
                'request_id': event['params'].get('requestId'),
                'url': url,
                'method': event['params'].get('request', {}).get('method'),
                'headers': event['params'].get('request', {}).get('headers'),
                'type': event['params'].get('type'),
                'timestamp': event['params'].get('timestamp'),
            },
        )

    def _on_response(event: dict[str, Any]) -> None:
        resp = event.get('params', {}).get('response', {})
        url = resp.get('url', '')
        if filter and filter not in url:
            return
        _emit(
            {
                'kind': 'response',
                'request_id': event['params'].get('requestId'),
                'url': url,
                'status': resp.get('status'),
                'mime_type': resp.get('mimeType'),
                'headers': resp.get('headers'),
                'timestamp': event['params'].get('timestamp'),
            },
        )

    async with open_browser(opts) as (_browser, tab):
        await tab.enable_network_events()
        cb_ids: list[int] = []
        try:
            if kind_lc in ('request', 'both'):
                cb_ids.append(
                    await tab.on(NetworkEvent.REQUEST_WILL_BE_SENT.value, _on_request),
                )
            if kind_lc in ('response', 'both'):
                cb_ids.append(
                    await tab.on(NetworkEvent.RESPONSE_RECEIVED.value, _on_response),
                )
            await done.wait()
        finally:
            for cb_id in cb_ids:
                with contextlib.suppress(Exception):
                    await tab.remove_callback(cb_id)
            with contextlib.suppress(Exception):
                await tab.disable_network_events()


# =============================================================================
# Network interception (Fetch domain) — wrap pattern
# =============================================================================
#
# Each interceptor command sets up Fetch on the active session, registers a
# handler, then spawns the user-supplied inner command as a subprocess. The
# subprocess connects to the same session (--session NAME) and shares the
# same browser. Fetch is target-scoped from the browser's perspective, so the
# wrapping connection's handler responds to the requests the subprocess makes.
# When the subprocess exits, Fetch is disabled and the wrapper exits with the
# subprocess's exit code.

_HandlerFactory = Callable[[Any], Callable[[dict[str, Any]], Awaitable[None]]]


def _strip_leading_dash_dash(args: list[str]) -> list[str]:
    """Drop a leading `--` separator if the user wrote one."""
    return args[1:] if args and args[0] == '--' else args


def _resolve_resource_types(names: list[str]) -> list[ResourceType]:
    """Map case-insensitive names like 'image' to ResourceType.IMAGE."""
    out: list[ResourceType] = []
    for raw in names:
        token = raw.upper().replace('-', '_')
        try:
            out.append(ResourceType[token])
        except KeyError as e:
            valid = ', '.join(rt.name for rt in ResourceType)
            raise CliError(
                f'unknown resource type {raw!r}. Valid: {valid}.',
                exit_code=2,
            ) from e
    return out


def _parse_header_pairs(raws: list[str]) -> list[dict[str, str]]:
    """Parse 'K: V' or 'K=V' header strings into CDP HeaderEntry dicts."""
    out: list[dict[str, str]] = []
    for raw in raws:
        if ':' in raw:
            name, _, value = raw.partition(':')
        elif '=' in raw:
            name, _, value = raw.partition('=')
        else:
            raise CliError(
                f'header must be "Name: Value" or "Name=Value" (got {raw!r}).',
                exit_code=2,
            )
        name, value = name.strip(), value.strip()
        if not name:
            raise CliError(f'header name is empty in {raw!r}.', exit_code=2)
        out.append({'name': name, 'value': value})
    return out


def _resolve_error_reason(name: str) -> ErrorReason:
    upper = name.upper().replace('-', '_')
    try:
        return ErrorReason[upper]
    except KeyError as e:
        valid = ', '.join(er.name for er in ErrorReason)
        raise CliError(
            f'unknown error reason {name!r}. Valid: {valid}.',
            exit_code=2,
        ) from e


async def _run_with_interceptor(
    opts: GlobalOptions,
    inner_args: list[str],
    handler_factory: _HandlerFactory,
    *,
    enable_kwargs: dict[str, Any] | None = None,
) -> int:
    """Set up Fetch on the active session, spawn the inner command, return its exit code."""
    if not opts.session and not opts.connect:
        raise CliError(
            'network interception requires --session NAME or --connect WS_URL '
            '(the inner command runs as a subprocess against the same browser).',
            exit_code=2,
        )
    if not inner_args:
        raise CliError(
            'missing inner command. Use: network <subcmd> [opts] [--] CMD [ARGS...]',
            exit_code=2,
        )

    async with open_browser(opts) as (_browser, tab):
        await tab.enable_fetch_events(**(enable_kwargs or {}))
        handler = handler_factory(tab)
        cb_id = await tab.on(FetchEvent.REQUEST_PAUSED.value, handler)
        try:
            sub_argv: list[str] = [sys.argv[0]]
            if opts.session:
                sub_argv += ['--session', opts.session]
            if opts.connect:
                sub_argv += ['--connect', opts.connect]
            if opts.output != 'text':
                sub_argv += ['--output', opts.output]
            sub_argv += inner_args

            proc = await asyncio.create_subprocess_exec(*sub_argv)
            rc = await proc.wait()
            return rc if rc is not None else 1
        finally:
            with contextlib.suppress(Exception):
                await tab.remove_callback(cb_id)
            with contextlib.suppress(Exception):
                await tab.disable_fetch_events()


def _exit_with(rc: int) -> None:
    """Propagate the subprocess's exit code as our own."""
    raise typer.Exit(rc)


@group_app.command(
    'block',
    help='Block matching resource types for the duration of an inner command.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network block -t Image -t Stylesheet \\\n'
        '    -- get https://heavy-site.com\n'
        '  pydoll-cli --session s network block -t Font -- screenshot https://x.com -o s.png\n'
    ),
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@run_async
async def block(
    ctx: typer.Context,
    types: Annotated[
        list[str] | None,
        typer.Option(
            '--type',
            '-t',
            help='Resource type to block; repeat to block multiple. '
                 'Names: Document, Stylesheet, Image, Media, Font, Script, XHR, Fetch, '
                 'Prefetch, EventSource, WebSocket, Manifest, Ping, Other (case-insensitive).',
        ),
    ] = None,
) -> None:
    if not types:
        raise CliError('network block: at least one --type TYPE is required.', exit_code=2)
    blocked = set(_resolve_resource_types(types))
    inner_args = _strip_leading_dash_dash(list(ctx.args))
    opts: GlobalOptions = ctx.obj

    def _factory(tab: Any) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def handler(event: dict[str, Any]) -> None:
            params = event.get('params', {})
            rid = params.get('requestId')
            if not rid:
                return
            try:
                resource = params.get('resourceType')
                rtype = ResourceType(resource) if resource else None
            except ValueError:
                rtype = None
            if rtype is not None and rtype in blocked:
                with contextlib.suppress(Exception):
                    await tab.fail_request(rid, ErrorReason.BLOCKED_BY_CLIENT)
            else:
                with contextlib.suppress(Exception):
                    await tab.continue_request(rid)
        return handler

    rc = await _run_with_interceptor(opts, inner_args, _factory)
    _exit_with(rc)


@group_app.command(
    'mock',
    help='Mock matching requests with a canned response, for the duration of an inner command.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network mock -p /api/me --status 200 --body fixture.json \\\n'
        '    -- get https://app.com\n'
        '  pydoll-cli --session s network mock -p /api/items --status 503 --body err.json \\\n'
        '    -H "content-type: application/json" -- get https://app.com\n'
    ),
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@run_async
async def mock(
    ctx: typer.Context,
    pattern: Annotated[
        str,
        typer.Option('--pattern', '-p', help='Substring matched against the request URL.'),
    ],
    body: Annotated[
        Path,
        typer.Option('--body', help='File whose bytes become the response body.'),
    ],
    status: Annotated[
        int,
        typer.Option('--status', help='HTTP status code (default 200).'),
    ] = 200,
    headers: Annotated[
        list[str] | None,
        typer.Option(
            '--header',
            '-H',
            help='Response header "Name: Value" or "Name=Value" (repeat).',
        ),
    ] = None,
) -> None:
    if not body.exists():
        raise CliError(f'network mock: body file does not exist: {body}', exit_code=2)
    body_bytes = body.read_bytes()
    body_b64 = base64.b64encode(body_bytes).decode('ascii')
    header_entries = _parse_header_pairs(headers or [])
    inner_args = _strip_leading_dash_dash(list(ctx.args))
    opts: GlobalOptions = ctx.obj

    def _factory(tab: Any) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def handler(event: dict[str, Any]) -> None:
            params = event.get('params', {})
            rid = params.get('requestId')
            if not rid:
                return
            url = params.get('request', {}).get('url', '')
            if pattern in url:
                with contextlib.suppress(Exception):
                    await tab.fulfill_request(
                        rid,
                        response_code=status,
                        response_headers=header_entries or None,
                        body=body_b64,
                    )
            else:
                with contextlib.suppress(Exception):
                    await tab.continue_request(rid)
        return handler

    rc = await _run_with_interceptor(opts, inner_args, _factory)
    _exit_with(rc)


@group_app.command(
    'inject-header',
    help='Add request headers to matching requests for the duration of an inner command.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network inject-header -p /api/ \\\n'
        '    -H "Authorization: Bearer xyz" -- request GET https://app.com/api/me\n'
    ),
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@run_async
async def inject_header(
    ctx: typer.Context,
    pattern: Annotated[
        str,
        typer.Option('--pattern', '-p', help='Substring matched against the request URL.'),
    ],
    headers: Annotated[
        list[str] | None,
        typer.Option(
            '--header',
            '-H',
            help='Header to inject "Name: Value" or "Name=Value" (repeat).',
        ),
    ] = None,
) -> None:
    if not headers:
        raise CliError(
            'network inject-header: at least one -H "Name: Value" is required.',
            exit_code=2,
        )
    new_headers = _parse_header_pairs(headers)
    inner_args = _strip_leading_dash_dash(list(ctx.args))
    opts: GlobalOptions = ctx.obj

    def _factory(tab: Any) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def handler(event: dict[str, Any]) -> None:
            params = event.get('params', {})
            rid = params.get('requestId')
            if not rid:
                return
            req = params.get('request', {})
            url = req.get('url', '')
            if pattern in url:
                # Merge new headers onto existing ones; new wins on collision.
                existing = req.get('headers', {}) or {}
                merged: dict[str, str] = {str(k): str(v) for k, v in existing.items()}
                for h in new_headers:
                    merged[h['name']] = h['value']
                merged_list = [{'name': k, 'value': v} for k, v in merged.items()]
                with contextlib.suppress(Exception):
                    await tab.continue_request(rid, headers=merged_list)
            else:
                with contextlib.suppress(Exception):
                    await tab.continue_request(rid)
        return handler

    rc = await _run_with_interceptor(opts, inner_args, _factory)
    _exit_with(rc)


@group_app.command(
    'fail',
    help='Fail matching requests for the duration of an inner command.',
    epilog=(
        'Examples:\n'
        '  pydoll-cli --session s network fail -p /track/ -- get https://app.com\n'
        '  pydoll-cli --session s network fail -p /api/slow --reason CONNECTION_REFUSED \\\n'
        '    -- get https://app.com\n'
    ),
    context_settings={'allow_extra_args': True, 'ignore_unknown_options': True},
)
@run_async
async def fail(
    ctx: typer.Context,
    pattern: Annotated[
        str,
        typer.Option('--pattern', '-p', help='Substring matched against the request URL.'),
    ],
    reason: Annotated[
        str,
        typer.Option(
            '--reason',
            help=(
                'ErrorReason name (default TIMED_OUT). Other useful values: FAILED, ABORTED, '
                'CONNECTION_REFUSED, CONNECTION_RESET, NAME_NOT_RESOLVED, BLOCKED_BY_CLIENT.'
            ),
        ),
    ] = 'TIMED_OUT',
) -> None:
    error = _resolve_error_reason(reason)
    inner_args = _strip_leading_dash_dash(list(ctx.args))
    opts: GlobalOptions = ctx.obj

    def _factory(tab: Any) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def handler(event: dict[str, Any]) -> None:
            params = event.get('params', {})
            rid = params.get('requestId')
            if not rid:
                return
            url = params.get('request', {}).get('url', '')
            if pattern in url:
                with contextlib.suppress(Exception):
                    await tab.fail_request(rid, error)
            else:
                with contextlib.suppress(Exception):
                    await tab.continue_request(rid)
        return handler

    rc = await _run_with_interceptor(opts, inner_args, _factory)
    _exit_with(rc)
