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
        attached=True,
        browser_context_id=None,
        target_id='target-abc',
        created_target=False,
    )
    p = tmp_path / 'foo.json'
    p.write_text(state.to_json())
    loaded = session.SessionState.from_file(p)
    assert loaded == state


def test_state_back_compat_old_file_without_created_target(tmp_path: Path):
    """Pre-0.3.2 state files (no created_target) should load with default True."""
    p = tmp_path / 'old.json'
    p.write_text(
        '{"name":"old","pid":0,"port":9222,'
        '"ws_url":"ws://127.0.0.1:9222/devtools/browser/x",'
        '"user_data_dir":"","browser":"chrome","binary":"",'
        '"started_at":0.0,"attached":true,"browser_context_id":null,'
        '"target_id":"abc"}'
    )
    loaded = session.SessionState.from_file(p)
    assert loaded.target_id == 'abc'
    assert loaded.created_target is True


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
