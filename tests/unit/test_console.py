"""Unit tests for the `console` command group.

No browser is involved: synthetic CDP events are pushed through `_normalize`
and the filter/sort helpers, mirroring how `test_network_interception.py`
drives Fetch handlers with hand-built events.
"""

from __future__ import annotations

from typing import Any

from typer.testing import CliRunner

from pydoll_cli.cli import app
from pydoll_cli.commands import console as console_mod

runner = CliRunner()


# ---- event builders --------------------------------------------------------


def _console_event(
    call_type: str = 'log',
    args: list[dict[str, Any]] | None = None,
    *,
    timestamp: float = 1000.0,
    frames: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        'type': call_type,
        'args': args if args is not None else [{'type': 'string', 'value': 'hello'}],
        'timestamp': timestamp,
        'executionContextId': 1,
    }
    if frames is not None:
        params['stackTrace'] = {'callFrames': frames}
    return {'method': 'Runtime.consoleAPICalled', 'params': params}


def _exception_event(
    description: str = 'ReferenceError: undefinedFn is not defined',
    *,
    timestamp: float = 2000.0,
) -> dict[str, Any]:
    return {
        'method': 'Runtime.exceptionThrown',
        'params': {
            'timestamp': timestamp,
            'exceptionDetails': {
                'text': 'Uncaught',
                'url': 'https://app.com/app.js',
                'lineNumber': 42,
                'columnNumber': 7,
                'exception': {'type': 'object', 'description': description},
            },
        },
    }


def _entry_event(
    source: str = 'network',
    level: str = 'error',
    text: str = 'Failed to load resource: 404',
    *,
    timestamp: float = 1500.0,
) -> dict[str, Any]:
    return {
        'method': 'Log.entryAdded',
        'params': {
            'entry': {
                'source': source,
                'level': level,
                'text': text,
                'timestamp': timestamp,
                'url': 'https://app.com/missing.png',
                'lineNumber': 3,
            },
        },
    }


# ---- _stringify_arg --------------------------------------------------------


def test_stringify_primitive_string_is_verbatim():
    assert console_mod._stringify_arg({'type': 'string', 'value': 'hi'}) == 'hi'


def test_stringify_primitive_number_and_bool():
    assert console_mod._stringify_arg({'type': 'number', 'value': 42}) == '42'
    assert console_mod._stringify_arg({'type': 'boolean', 'value': True}) == 'true'


def test_stringify_object_without_value_uses_description():
    """Objects carry no `value` — without the fallback they render as None."""
    obj = {'type': 'object', 'className': 'Object', 'description': 'Object'}
    assert console_mod._stringify_arg(obj) == 'Object'


def test_stringify_object_falls_back_to_preview_properties():
    obj = {
        'type': 'object',
        'preview': {'properties': [{'name': 'a', 'value': '1'}, {'name': 'b', 'value': '2'}]},
    }
    assert console_mod._stringify_arg(obj) == '{a: 1, b: 2}'


def test_stringify_bare_type_is_last_resort():
    assert console_mod._stringify_arg({'type': 'undefined'}) == 'undefined'


# ---- _normalize: shape -----------------------------------------------------


def test_normalize_console_api_shape():
    frames = [
        {
            'functionName': 'render',
            'url': 'https://app.com/app.js',
            'lineNumber': 12,
            'columnNumber': 4,
        },
    ]
    rec = console_mod._normalize(
        _console_event('error', [{'type': 'string', 'value': 'boom'}], frames=frames),
        'console-api',
    )
    assert rec == {
        'source': 'console-api',
        'level': 'error',
        'type': 'error',
        'text': 'boom',
        'url': 'https://app.com/app.js',
        'line': 12,
        'column': 4,
        'timestamp': 1000.0,
        'stack': [
            {'function': 'render', 'url': 'https://app.com/app.js', 'line': 12, 'column': 4},
        ],
    }


def test_normalize_console_api_joins_args_with_spaces():
    rec = console_mod._normalize(
        _console_event(
            'log',
            [{'type': 'string', 'value': 'a'}, {'type': 'number', 'value': 1}],
        ),
        'console-api',
    )
    assert rec is not None
    assert rec['text'] == 'a 1'


def test_normalize_console_api_level_mapping():
    def level_of(call_type: str) -> str | None:
        rec = console_mod._normalize(_console_event(call_type), 'console-api')
        return None if rec is None else rec['level']

    assert level_of('warning') == 'warning'
    assert level_of('error') == 'error'
    assert level_of('debug') == 'debug'
    assert level_of('info') == 'info'
    # Everything decorative collapses to 'log'.
    assert level_of('trace') == 'log'
    assert level_of('dir') == 'log'
    assert level_of('table') == 'log'
    assert level_of('startGroup') == 'log'
    # …but `type` keeps the raw CDP call type.
    rec = console_mod._normalize(_console_event('table'), 'console-api')
    assert rec is not None
    assert rec['type'] == 'table'


def test_normalize_exception_shape():
    rec = console_mod._normalize(_exception_event(), 'exception')
    assert rec is not None
    assert rec['source'] == 'exception'
    assert rec['level'] == 'error'
    assert rec['text'] == 'ReferenceError: undefinedFn is not defined'
    assert rec['url'] == 'https://app.com/app.js'
    assert rec['line'] == 42
    assert rec['column'] == 7


def test_normalize_exception_falls_back_to_text():
    event = _exception_event()
    del event['params']['exceptionDetails']['exception']
    rec = console_mod._normalize(event, 'exception')
    assert rec is not None
    assert rec['text'] == 'Uncaught'


def test_normalize_log_entry_uses_entry_source_and_level():
    rec = console_mod._normalize(_entry_event(), 'log-entry')
    assert rec is not None
    assert rec['source'] == 'network'
    assert rec['level'] == 'error'
    assert rec['type'] == 'entry'
    assert rec['text'] == 'Failed to load resource: 404'
    assert rec['line'] == 3


def test_normalize_drops_console_api_log_entries():
    """Some Chrome versions mirror console calls into Log; Runtime covers them."""
    mirrored = _entry_event(source='console-api', level='log', text='hello')
    assert console_mod._normalize(mirrored, 'log-entry') is None


# ---- sorting ---------------------------------------------------------------


def test_records_merge_in_timestamp_order():
    """Runtime and Log replay as two separate bursts; sorting re-interleaves them."""
    recs = [
        console_mod._normalize(_exception_event(timestamp=2000.0), 'exception'),
        console_mod._normalize(_console_event(timestamp=1000.0), 'console-api'),
        console_mod._normalize(_entry_event(timestamp=1500.0), 'log-entry'),
    ]
    ordered = sorted([r for r in recs if r], key=console_mod._sort_key)
    assert [r['timestamp'] for r in ordered] == [1000.0, 1500.0, 2000.0]
    assert [r['source'] for r in ordered] == ['console-api', 'network', 'exception']


def test_sort_key_tolerates_missing_timestamp():
    assert console_mod._sort_key({'timestamp': None}) == 0.0
    assert console_mod._sort_key({}) == 0.0


# ---- filters ---------------------------------------------------------------


def _sample_records() -> list[dict[str, Any]]:
    recs = [
        console_mod._normalize(_console_event('log'), 'console-api'),
        console_mod._normalize(
            _console_event('warning', [{'type': 'string', 'value': 'hydration mismatch'}]),
            'console-api',
        ),
        console_mod._normalize(_exception_event(), 'exception'),
        console_mod._normalize(_entry_event(), 'log-entry'),
    ]
    return [r for r in recs if r]


def _keep(**kwargs: Any) -> list[dict[str, Any]]:
    kwargs.setdefault('levels', None)
    kwargs.setdefault('kinds', None)
    kwargs.setdefault('substring', None)
    return [r for r in _sample_records() if console_mod._matches(r, **kwargs)]


def test_default_filters_emit_every_level():
    assert len(_keep()) == 4


def test_level_filter_narrows():
    kept = _keep(levels=console_mod._csv_set('error,warning'))
    assert {r['level'] for r in kept} == {'error', 'warning'}
    assert len(kept) == 3


def test_kind_filter_matches_source():
    kept = _keep(kinds=console_mod._csv_set('network'))
    assert len(kept) == 1
    assert kept[0]['source'] == 'network'

    kept = _keep(kinds=console_mod._csv_set('console-api,exception'))
    assert {r['source'] for r in kept} == {'console-api', 'exception'}


def test_text_filter_is_substring_on_text():
    kept = _keep(substring='hydrat')
    assert len(kept) == 1
    assert 'hydration' in kept[0]['text']


def test_csv_set_is_case_insensitive_and_trims():
    assert console_mod._csv_set(' Error , WARNING ') == {'error', 'warning'}
    assert console_mod._csv_set(None) is None
    assert console_mod._csv_set('  ,  ') is None


# ---- text rendering --------------------------------------------------------


def test_text_line_includes_level_source_text_and_location():
    rec = console_mod._normalize(_exception_event(), 'exception')
    assert rec is not None
    line = console_mod._text_line(rec)
    assert 'error' in line
    assert 'exception' in line
    assert 'ReferenceError' in line
    assert '(https://app.com/app.js:42)' in line


# ---- wiring ----------------------------------------------------------------


def test_console_group_is_registered():
    result = runner.invoke(app, ['console', '--help'])
    assert result.exit_code == 0
    assert 'logs' in result.stdout
    assert 'watch' in result.stdout


def test_console_logs_help_lists_filters():
    result = runner.invoke(app, ['console', 'logs', '--help'])
    assert result.exit_code == 0
    for flag in ('--level', '--kind', '--filter', '--settle', '--duration', '--clear'):
        assert flag in result.stdout


def test_console_watch_help_lists_replay_toggle():
    result = runner.invoke(app, ['console', 'watch', '--help'])
    assert result.exit_code == 0
    assert '--no-replay' in result.stdout
    assert '--max-events' in result.stdout
