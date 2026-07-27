"""Tests for `install-skill` destination resolution.

The failure mode worth guarding is a silent one: writing SKILL.md somewhere
Claude Code never reads, while still reporting success.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from pydoll_cli.cli import app
from pydoll_cli.commands import install_skill

runner = CliRunner()


# ---- user scope honours CLAUDE_CONFIG_DIR -------------------------------


def test_user_scope_defaults_to_dot_claude(tmp_path: Path, monkeypatch):
    monkeypatch.delenv('CLAUDE_CONFIG_DIR', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path))

    assert install_skill._skills_dir_for_scope('user') == tmp_path / '.claude' / 'skills'


def test_user_scope_follows_claude_config_dir(tmp_path: Path, monkeypatch):
    # A relocated config tree takes skills with it; ~/.claude is then dead.
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / '.claude-personal'))
    monkeypatch.setenv('HOME', str(tmp_path))

    assert install_skill._skills_dir_for_scope('user') == tmp_path / '.claude-personal' / 'skills'


def test_user_scope_expands_tilde_in_override(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', '~/.claude-personal')
    monkeypatch.setenv('HOME', str(tmp_path))

    assert install_skill._skills_dir_for_scope('user') == tmp_path / '.claude-personal' / 'skills'


def test_project_scope_ignores_claude_config_dir(tmp_path: Path, monkeypatch):
    # Project scope is anchored to the cwd, not the user config tree.
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'elsewhere'))
    monkeypatch.chdir(tmp_path)

    assert install_skill._skills_dir_for_scope('project') == tmp_path / '.claude' / 'skills'


# ---- end-to-end through the command ------------------------------------


def test_install_user_scope_writes_into_the_override_dir(tmp_path: Path, monkeypatch):
    cfg = tmp_path / '.claude-personal'
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(cfg))
    monkeypatch.setenv('HOME', str(tmp_path))

    result = runner.invoke(app, ['install-skill', '--scope', 'user'])
    assert result.exit_code == 0, result.output

    assert (cfg / 'skills' / 'pydoll-cli' / 'SKILL.md').is_file()
    assert not (tmp_path / '.claude').exists()  # nothing written to the dead path


def test_install_refuses_to_overwrite_without_force(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(tmp_path / 'cfg'))
    monkeypatch.setenv('HOME', str(tmp_path))

    assert runner.invoke(app, ['install-skill', '--scope', 'user']).exit_code == 0
    again = runner.invoke(app, ['install-skill', '--scope', 'user'])
    assert again.exit_code != 0
    assert 'already exists' in again.output

    forced = runner.invoke(app, ['install-skill', '--scope', 'user', '--force'])
    assert forced.exit_code == 0, forced.output
