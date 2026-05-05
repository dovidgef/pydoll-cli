"""Unit tests for the four network interception commands (block / mock / inject-header / fail).

Each test exercises:
1. Argument validation surfaces useful exit codes.
2. The Fetch handler routes matched vs unmatched requests to the right pydoll
   call (fail_request, fulfill_request, continue_request, etc.).

We don't actually launch a browser or a subprocess. The wrap helper is patched
so the inner subprocess is replaced with a no-op that returns 0; the test then
manually invokes the registered handler with synthetic Fetch.requestPaused
events to verify routing.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydoll.protocol.network.types import ErrorReason, ResourceType
from typer.testing import CliRunner

from pydoll_cli.cli import app
from pydoll_cli.commands import network as network_mod
from pydoll_cli.output import CliError

runner = CliRunner()


# ---- Helper: stub _run_with_interceptor to capture the registered handler ---


class _Captured:
    handler = None
    inner_args: list[str] | None = None


@contextlib.contextmanager
def _capture_handler(tab):
    """Patch _run_with_interceptor so we capture the handler instead of subprocessing."""
    captured = _Captured()

    async def _stub_run(opts, inner_args, handler_factory, *, enable_kwargs=None):
        captured.inner_args = list(inner_args)
        captured.handler = handler_factory(tab)
        return 0  # pretend the inner subprocess succeeded

    with patch.object(network_mod, '_run_with_interceptor', side_effect=_stub_run):
        yield captured


def _fetch_event(rid: str, url: str, *, resource_type: str = 'XHR') -> dict:
    return {
        'method': 'Fetch.requestPaused',
        'params': {
            'requestId': rid,
            'resourceType': resource_type,
            'request': {
                'url': url,
                'method': 'GET',
                'headers': {'accept': 'application/json'},
            },
        },
    }


def _make_tab() -> MagicMock:
    tab = MagicMock()
    tab.continue_request = AsyncMock()
    tab.fail_request = AsyncMock()
    tab.fulfill_request = AsyncMock()
    return tab


# ---- _strip_leading_dash_dash ----------------------------------------------


def test_strip_dash_dash_removes_leading():
    assert network_mod._strip_leading_dash_dash(['--', 'get', 'URL']) == ['get', 'URL']


def test_strip_dash_dash_passes_through_when_absent():
    assert network_mod._strip_leading_dash_dash(['get', 'URL']) == ['get', 'URL']


# ---- _resolve_resource_types -----------------------------------------------


def test_resolve_resource_types_case_insensitive():
    out = network_mod._resolve_resource_types(['image', 'StyleSheet', 'XHR'])
    assert out == [ResourceType.IMAGE, ResourceType.STYLESHEET, ResourceType.XHR]


def test_resolve_resource_types_unknown_raises():
    with pytest.raises(CliError):
        network_mod._resolve_resource_types(['Pizza'])


# ---- _parse_header_pairs ---------------------------------------------------


def test_parse_headers_colon_form():
    assert network_mod._parse_header_pairs(['Authorization: Bearer xyz']) == [
        {'name': 'Authorization', 'value': 'Bearer xyz'},
    ]


def test_parse_headers_equals_form():
    assert network_mod._parse_header_pairs(['x-foo=1']) == [{'name': 'x-foo', 'value': '1'}]


def test_parse_headers_bad_format_raises():
    with pytest.raises(CliError):
        network_mod._parse_header_pairs(['no-separator'])


# ---- _resolve_error_reason -------------------------------------------------


def test_resolve_error_reason_default_naming():
    assert network_mod._resolve_error_reason('TIMED_OUT') == ErrorReason.TIMED_OUT
    assert network_mod._resolve_error_reason('connection-refused') == ErrorReason.CONNECTION_REFUSED


def test_resolve_error_reason_unknown_raises():
    with pytest.raises(CliError):
        network_mod._resolve_error_reason('NOT_A_REASON')


# ---- network block ---------------------------------------------------------


def test_block_requires_type():
    result = runner.invoke(app, ['--session', 's', 'network', 'block', '--', 'get', 'URL'])
    assert result.exit_code == 2


def test_block_unknown_type_exits_2():
    result = runner.invoke(
        app,
        ['--session', 's', 'network', 'block', '-t', 'Pizza', '--', 'get', 'URL'],
    )
    assert result.exit_code == 2


def test_block_handler_fails_matched_continues_others():
    tab = _make_tab()
    with _capture_handler(tab) as cap:
        result = runner.invoke(
            app,
            [
                '--session',
                's',
                'network',
                'block',
                '-t',
                'Image',
                '-t',
                'Stylesheet',
                '--',
                'get',
                'https://x.com',
            ],
        )
    assert result.exit_code == 0, result.stdout
    assert cap.inner_args == ['get', 'https://x.com']
    assert cap.handler is not None

    # Matched: an Image request is failed.
    asyncio.run(cap.handler(_fetch_event('r1', 'https://x.com/a.png', resource_type='Image')))
    tab.fail_request.assert_awaited_once_with('r1', ErrorReason.BLOCKED_BY_CLIENT)
    tab.continue_request.assert_not_called()

    # Unmatched: a Document request is continued.
    tab.fail_request.reset_mock()
    asyncio.run(cap.handler(_fetch_event('r2', 'https://x.com', resource_type='Document')))
    tab.continue_request.assert_awaited_once_with('r2')
    tab.fail_request.assert_not_called()


# ---- network mock ----------------------------------------------------------


def test_mock_missing_body_exits_2(tmp_path: Path):
    bad = tmp_path / 'nope.json'
    result = runner.invoke(
        app,
        [
            '--session',
            's',
            'network',
            'mock',
            '-p',
            '/api/',
            '--body',
            str(bad),
            '--',
            'get',
            'URL',
        ],
    )
    assert result.exit_code == 2


def test_mock_handler_fulfills_matched(tmp_path: Path):
    body_file = tmp_path / 'body.json'
    body_file.write_bytes(b'{"hello":"world"}')
    tab = _make_tab()
    with _capture_handler(tab) as cap:
        result = runner.invoke(
            app,
            [
                '--session',
                's',
                'network',
                'mock',
                '-p',
                '/api/me',
                '--status',
                '200',
                '--body',
                str(body_file),
                '-H',
                'content-type: application/json',
                '--',
                'get',
                'https://app.com',
            ],
        )
    assert result.exit_code == 0, result.stdout
    assert cap.inner_args == ['get', 'https://app.com']

    asyncio.run(cap.handler(_fetch_event('r1', 'https://app.com/api/me')))
    tab.fulfill_request.assert_awaited_once()
    args, kwargs = tab.fulfill_request.call_args
    assert args[0] == 'r1'
    assert kwargs['response_code'] == 200
    assert kwargs['response_headers'] == [{'name': 'content-type', 'value': 'application/json'}]
    expected_b64 = base64.b64encode(b'{"hello":"world"}').decode('ascii')
    assert kwargs['body'] == expected_b64

    # Unmatched URL → continue.
    tab.fulfill_request.reset_mock()
    asyncio.run(cap.handler(_fetch_event('r2', 'https://app.com/other')))
    tab.continue_request.assert_awaited_once_with('r2')
    tab.fulfill_request.assert_not_called()


# ---- network inject-header --------------------------------------------------


def test_inject_header_requires_at_least_one():
    result = runner.invoke(
        app,
        ['--session', 's', 'network', 'inject-header', '-p', '/api/', '--', 'get', 'URL'],
    )
    assert result.exit_code == 2


def test_inject_header_merges_with_existing():
    tab = _make_tab()
    with _capture_handler(tab) as cap:
        result = runner.invoke(
            app,
            [
                '--session',
                's',
                'network',
                'inject-header',
                '-p',
                '/api/',
                '-H',
                'Authorization: Bearer xyz',
                '-H',
                'x-trace=abc',
                '--',
                'get',
                'https://app.com',
            ],
        )
    assert result.exit_code == 0, result.stdout

    asyncio.run(cap.handler(_fetch_event('r1', 'https://app.com/api/me')))
    args, kwargs = tab.continue_request.call_args
    assert args[0] == 'r1'
    headers = {h['name']: h['value'] for h in kwargs['headers']}
    assert headers['accept'] == 'application/json'  # existing preserved
    assert headers['Authorization'] == 'Bearer xyz'  # new added
    assert headers['x-trace'] == 'abc'

    # Unmatched URL → continue without headers kwarg.
    tab.continue_request.reset_mock()
    asyncio.run(cap.handler(_fetch_event('r2', 'https://app.com/other')))
    tab.continue_request.assert_awaited_once_with('r2')


# ---- network fail ----------------------------------------------------------


def test_fail_unknown_reason_exits_2():
    result = runner.invoke(
        app,
        [
            '--session',
            's',
            'network',
            'fail',
            '-p',
            '/api/',
            '--reason',
            'PIZZA',
            '--',
            'get',
            'URL',
        ],
    )
    assert result.exit_code == 2


def test_fail_handler_fails_matched():
    tab = _make_tab()
    with _capture_handler(tab) as cap:
        result = runner.invoke(
            app,
            [
                '--session',
                's',
                'network',
                'fail',
                '-p',
                '/track/',
                '--reason',
                'CONNECTION_REFUSED',
                '--',
                'get',
                'https://app.com',
            ],
        )
    assert result.exit_code == 0, result.stdout

    asyncio.run(cap.handler(_fetch_event('r1', 'https://app.com/track/click')))
    tab.fail_request.assert_awaited_once_with('r1', ErrorReason.CONNECTION_REFUSED)

    tab.fail_request.reset_mock()
    asyncio.run(cap.handler(_fetch_event('r2', 'https://app.com/api/data')))
    tab.continue_request.assert_awaited_once_with('r2')


def test_fail_default_reason_is_timed_out():
    tab = _make_tab()
    with _capture_handler(tab) as cap:
        result = runner.invoke(
            app,
            ['--session', 's', 'network', 'fail', '-p', '/track/', '--', 'get', 'https://app.com'],
        )
    assert result.exit_code == 0, result.stdout
    asyncio.run(cap.handler(_fetch_event('r1', 'https://app.com/track/x')))
    tab.fail_request.assert_awaited_once_with('r1', ErrorReason.TIMED_OUT)


# ---- _run_with_interceptor session validation ------------------------------


def test_interceptor_requires_session():
    """Without --session/--connect, all interceptor commands must error out."""
    for cmd in (
        ['network', 'block', '-t', 'Image', '--', 'get', 'URL'],
        ['network', 'mock', '-p', '/x', '--body', '/dev/null', '--', 'get', 'URL'],
        ['network', 'inject-header', '-p', '/x', '-H', 'a: b', '--', 'get', 'URL'],
        ['network', 'fail', '-p', '/x', '--', 'get', 'URL'],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 2, (cmd, result.stdout)
