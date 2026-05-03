"""eval JS-error handling (exit code 7) and result-shape robustness."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from pydoll_cli.cli import app
from pydoll_cli.commands.eval_ import _extract_eval_result, _js_error_message
from pydoll_cli.output import EXIT_JS_ERROR, CliError

runner = CliRunner()


def _stub_browser(tab: MagicMock) -> contextlib.AbstractAsyncContextManager:
    @contextlib.asynccontextmanager
    async def _ctx(opts):
        yield (MagicMock(), tab)

    return _ctx


# ---- _extract_eval_result: shape robustness ---------------------------------


def test_extract_handles_wrapped_shape():
    wrapped = {'result': {'result': {'type': 'string', 'value': 'hi'}}}
    ro, ex = _extract_eval_result(wrapped)
    assert ro == {'type': 'string', 'value': 'hi'}
    assert ex is None


def test_extract_handles_unwrapped_shape():
    unwrapped = {'result': {'type': 'string', 'value': 'hi'}}
    ro, ex = _extract_eval_result(unwrapped)
    assert ro == {'type': 'string', 'value': 'hi'}
    assert ex is None


def test_extract_propagates_exception_details():
    wrapped = {
        'result': {
            'result': {'type': 'object', 'subtype': 'error', 'description': 'boom'},
            'exceptionDetails': {
                'text': 'Uncaught',
                'exception': {'description': 'ReferenceError: x is not defined'},
            },
        }
    }
    ro, ex = _extract_eval_result(wrapped)
    assert ro['subtype'] == 'error'
    assert ex is not None and ex['exception']['description'].startswith('ReferenceError')


def test_extract_tolerates_garbage():
    assert _extract_eval_result(None) == ({}, None)
    assert _extract_eval_result('not a dict') == ({}, None)
    assert _extract_eval_result({}) == ({}, None)


def test_js_error_message_prefers_exception_description():
    ro = {'subtype': 'error', 'className': 'SyntaxError'}
    ex = {'exception': {'description': 'SyntaxError: bad'}, 'text': 'Uncaught'}
    assert _js_error_message(ro, ex) == 'SyntaxError: bad'


def test_js_error_message_falls_back_to_remote_object():
    ro = {'subtype': 'error', 'description': 'TypeError: undefined'}
    assert _js_error_message(ro, None) == 'TypeError: undefined'


# ---- end-to-end: CliError → exit 7 ------------------------------------------


@pytest.mark.parametrize(
    'execute_return',
    [
        # Exception details surfaced.
        {
            'result': {
                'result': {
                    'type': 'object', 'subtype': 'error',
                    'className': 'SyntaxError', 'description': 'SyntaxError: oops',
                },
                'exceptionDetails': {
                    'text': 'Uncaught',
                    'exception': {'description': 'SyntaxError: oops'},
                },
            }
        },
        # Only the RemoteObject signals subtype=error (no exceptionDetails).
        {
            'result': {
                'result': {
                    'type': 'object', 'subtype': 'error',
                    'description': 'TypeError: bad',
                }
            }
        },
    ],
)
def test_eval_exits_7_on_js_error(execute_return):
    tab = MagicMock()
    tab.go_to = AsyncMock()
    tab.execute_script = AsyncMock(return_value=execute_return)

    with patch('pydoll_cli.commands.eval_.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'eval', 'https://example.com', '--script', 'foo()'],
        )

    assert result.exit_code == EXIT_JS_ERROR, (result.exit_code, result.stdout, result.stderr)


def test_eval_passes_await_promise_true():
    tab = MagicMock()
    tab.go_to = AsyncMock()
    tab.execute_script = AsyncMock(
        return_value={'result': {'result': {'type': 'string', 'value': 'ok'}}},
    )

    with patch('pydoll_cli.commands.eval_.open_browser', _stub_browser(tab)):
        result = runner.invoke(
            app,
            ['--output', 'json', 'eval', 'https://example.com', '--script', 'return 1'],
        )

    assert result.exit_code == 0, result.stdout
    tab.execute_script.assert_awaited_once_with(
        'return 1', return_by_value=True, await_promise=True,
    )


def test_clierror_exit_code_constant():
    err = CliError('boom', exit_code=EXIT_JS_ERROR)
    assert err.exit_code == 7
