"""Unit tests for session state serialization."""

from __future__ import annotations

from pathlib import Path

from pydoll_cli import session


def test_state_roundtrip(tmp_path: Path):
    state = session.SessionState(
        name='foo',
        pid=1234,
        port=9223,
        ws_url='ws://127.0.0.1:9223/devtools/browser/abc',
        user_data_dir='/tmp/pydoll/foo',
        browser='chrome',
        binary='/usr/bin/google-chrome',
        started_at=1700000000.0,
    )
    p = tmp_path / 'foo.json'
    p.write_text(state.to_json())
    loaded = session.SessionState.from_file(p)
    assert loaded == state


def test_list_states_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(session, 'sessions_dir', lambda: tmp_path / 'empty')
    assert session.list_states() == []


def test_load_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(session, 'sessions_dir', lambda: tmp_path)
    try:
        session.load('nope')
    except FileNotFoundError as e:
        assert 'No session' in str(e)
    else:
        raise AssertionError('expected FileNotFoundError')
