"""Unit + CLI tests for session profile garbage collection.

Covers orphan detection, prune candidate selection, `remove_async`,
`human_bytes`, and the `prune`/`rm`/`stop --purge`/`list` command wiring.
No real browser or process is launched: liveness and process kills are
monkeypatched.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pydoll_cli import session
from pydoll_cli.cli import app
from pydoll_cli.output import human_bytes

runner = CliRunner()


# ---- helpers ------------------------------------------------------------


@pytest.fixture
def cache(tmp_path: Path, monkeypatch) -> Path:
    """Redirect all session paths to a tmp dir."""
    monkeypatch.setattr(session, 'sessions_dir', lambda: tmp_path)
    return tmp_path


def _write_profile(root: Path, name: str, nbytes: int = 1024) -> Path:
    ud = root / name / 'user-data'
    ud.mkdir(parents=True, exist_ok=True)
    (ud / 'blob.bin').write_bytes(b'x' * nbytes)
    return root / name


def _write_state(
    root: Path,
    name: str,
    *,
    pid: int = 4242,
    started_at: float = 1_700_000_000.0,
    attached: bool = False,
) -> session.SessionState:
    state = session.SessionState(
        name=name,
        pid=pid,
        port=0,
        ws_url='',
        user_data_dir=str(root / name / 'user-data'),
        browser='chrome',
        binary='',
        started_at=started_at,
        attached=attached,
    )
    (root / f'{name}.json').write_text(state.to_json())
    return state


def _patch_alive(monkeypatch, alive_names: set[str]) -> None:
    async def _alive(state: session.SessionState) -> bool:
        return state.name in alive_names

    monkeypatch.setattr(session, 'alive', _alive)


# ---- orphan detection ---------------------------------------------------


def test_orphan_dirs(cache: Path):
    _write_profile(cache, 'registered')
    _write_state(cache, 'registered')
    _write_profile(cache, 'orphan')

    names = [p.name for p in session.orphan_dirs()]
    assert names == ['orphan']


def test_dir_size_sums_files(cache: Path):
    _write_profile(cache, 'a', nbytes=4096)
    assert session.dir_size(cache / 'a') == 4096


# ---- collect_prune_candidates ------------------------------------------


def test_collect_orphans_only(cache: Path, monkeypatch):
    _write_profile(cache, 'orphan')
    _write_profile(cache, 'live')
    _write_state(cache, 'live')
    _patch_alive(monkeypatch, {'live'})

    cands = asyncio.run(session.collect_prune_candidates(orphans=True))
    assert [(c.name, c.reason) for c in cands] == [('orphan', 'orphan')]


def test_collect_dead_only_excludes_alive(cache: Path, monkeypatch):
    _write_profile(cache, 'dead')
    _write_state(cache, 'dead')
    _write_profile(cache, 'live')
    _write_state(cache, 'live')
    _patch_alive(monkeypatch, {'live'})

    cands = asyncio.run(session.collect_prune_candidates(dead=True))
    assert [(c.name, c.reason) for c in cands] == [('dead', 'dead')]


def test_collect_dead_ignores_orphans(cache: Path, monkeypatch):
    _write_profile(cache, 'orphan')  # no state file
    _patch_alive(monkeypatch, set())

    cands = asyncio.run(session.collect_prune_candidates(dead=True))
    assert cands == []


def test_collect_older_than_filters(cache: Path, monkeypatch):
    fresh = _write_profile(cache, 'fresh')
    old = _write_profile(cache, 'old')
    now = 1_700_000_000.0
    monkeypatch.setattr(session.time, 'time', lambda: now)
    os.utime(fresh, (now, now))  # age 0 days
    os.utime(old, (now - 10 * 86400, now - 10 * 86400))  # 10 days old

    cands = asyncio.run(session.collect_prune_candidates(orphans=True, older_than_days=7))
    assert [c.name for c in cands] == ['old']


def test_collect_older_than_alone_selects_non_alive(cache: Path, monkeypatch):
    orphan = _write_profile(cache, 'orphan')
    _write_profile(cache, 'dead')
    _write_state(cache, 'dead', started_at=0.0)  # very old
    _patch_alive(monkeypatch, set())
    now = 1_700_000_000.0
    monkeypatch.setattr(session.time, 'time', lambda: now)
    os.utime(orphan, (now - 30 * 86400, now - 30 * 86400))

    cands = asyncio.run(session.collect_prune_candidates(older_than_days=7))
    assert sorted(c.name for c in cands) == ['dead', 'orphan']


def test_collect_requires_no_double_count(cache: Path, monkeypatch):
    # A dead registered session is not also an orphan (it has a state file).
    _write_profile(cache, 'dead')
    _write_state(cache, 'dead')
    _patch_alive(monkeypatch, set())

    cands = asyncio.run(session.collect_prune_candidates(orphans=True, dead=True))
    assert [c.name for c in cands] == ['dead']
    assert cands[0].reason == 'dead'


# ---- purge_profile / remove_async --------------------------------------


def test_purge_profile_removes_dir(cache: Path):
    _write_profile(cache, 'gone', nbytes=2048)
    freed = session.purge_profile('gone')
    assert freed == 2048
    assert not (cache / 'gone').exists()


def test_purge_profile_missing_is_noop(cache: Path):
    assert session.purge_profile('nope') == 0


def test_remove_async_owned(cache: Path, monkeypatch):
    monkeypatch.setattr(session, '_kill', lambda *a, **k: None)
    _write_profile(cache, 's', nbytes=1024)
    _write_state(cache, 's')

    freed = asyncio.run(session.remove_async('s'))
    assert freed == 1024
    assert not (cache / 's').exists()
    assert not (cache / 's.json').exists()


def test_remove_async_orphan(cache: Path):
    _write_profile(cache, 'orph', nbytes=512)
    freed = asyncio.run(session.remove_async('orph'))
    assert freed == 512
    assert not (cache / 'orph').exists()


def test_remove_async_missing_raises(cache: Path):
    with pytest.raises(FileNotFoundError):
        asyncio.run(session.remove_async('absent'))


# ---- human_bytes --------------------------------------------------------


@pytest.mark.parametrize(
    ('n', 'expected'),
    [
        (0, '0 B'),
        (512, '512 B'),
        (1024, '1.0 KB'),
        (1536, '1.5 KB'),
        (1024 * 1024, '1.0 MB'),
        (3 * 1024**3, '3.0 GB'),
    ],
)
def test_human_bytes(n: int, expected: str):
    assert human_bytes(n) == expected


# ---- CLI ----------------------------------------------------------------


def test_prune_no_flags_shows_help(cache: Path):
    result = runner.invoke(app, ['session', 'prune'])
    assert result.exit_code == 0, result.output
    assert '--orphans' in result.output


def test_prune_orphans_yes_deletes(cache: Path):
    _write_profile(cache, 'junk', nbytes=1024)
    result = runner.invoke(app, ['session', 'prune', '--orphans', '--yes'])
    assert result.exit_code == 0, result.output
    assert not (cache / 'junk').exists()
    assert 'pruned 1' in result.output


def test_prune_dry_run_keeps(cache: Path):
    _write_profile(cache, 'junk', nbytes=1024)
    result = runner.invoke(app, ['session', 'prune', '--orphans', '--dry-run'])
    assert result.exit_code == 0, result.output
    assert (cache / 'junk').exists()  # not deleted
    assert 'would reclaim' in result.output


def test_prune_json_without_yes_errors(cache: Path):
    _write_profile(cache, 'junk')
    result = runner.invoke(app, ['--output', 'json', 'session', 'prune', '--orphans'])
    assert result.exit_code == 2, result.output
    assert (cache / 'junk').exists()


def test_stop_purges_by_default(cache: Path, monkeypatch):
    monkeypatch.setattr(session, '_kill', lambda *a, **k: None)
    _write_profile(cache, 's', nbytes=1024)
    _write_state(cache, 's')

    result = runner.invoke(app, ['session', 'stop', 's'])
    assert result.exit_code == 0, result.output
    assert not (cache / 's').exists()
    assert not (cache / 's.json').exists()


def test_stop_no_purge_keeps_profile(cache: Path, monkeypatch):
    monkeypatch.setattr(session, '_kill', lambda *a, **k: None)
    _write_profile(cache, 's', nbytes=1024)
    _write_state(cache, 's')

    result = runner.invoke(app, ['session', 'stop', 's', '--no-purge'])
    assert result.exit_code == 0, result.output
    assert (cache / 's').exists()  # profile preserved for restart/login reuse
    assert not (cache / 's.json').exists()  # state still removed


def test_rm_deletes(cache: Path, monkeypatch):
    monkeypatch.setattr(session, '_kill', lambda *a, **k: None)
    _write_profile(cache, 'a', nbytes=1024)
    _write_state(cache, 'a')

    result = runner.invoke(app, ['session', 'rm', 'a'])
    assert result.exit_code == 0, result.output
    assert not (cache / 'a').exists()


def test_rm_missing_exit_6(cache: Path):
    result = runner.invoke(app, ['session', 'rm', 'absent'])
    assert result.exit_code == 6, result.output


def test_list_shows_orphans(cache: Path):
    _write_profile(cache, 'leftover', nbytes=1024)
    result = runner.invoke(app, ['session', 'list'])
    assert result.exit_code == 0, result.output
    assert 'leftover' in result.output
    assert 'orphan' in result.output
