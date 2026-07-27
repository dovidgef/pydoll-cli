"""Smoke tests: every subcommand --help renders without errors."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pydoll_cli.cli import app

runner = CliRunner()


def test_root_help():
    result = runner.invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'pydoll-cli' in result.stdout
    assert 'screenshot' in result.stdout
    assert 'session' in result.stdout


def test_version():
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0
    assert 'pydoll-cli' in result.stdout


@pytest.mark.parametrize(
    'cmd',
    [
        ['get', '--help'],
        ['screenshot', '--help'],
        ['pdf', '--help'],
        ['bundle', '--help'],
        ['source', '--help'],
        ['text', '--help'],
        ['eval', '--help'],
        ['query', '--help'],
        ['click', '--help'],
        ['type', '--help'],
        ['extract', '--help'],
        ['request', '--help'],
        ['shell', '--help'],
        ['run', '--help'],
        ['info', '--help'],
        ['browsers', '--help'],
        ['session', '--help'],
        ['session', 'start', '--help'],
        ['session', 'stop', '--help'],
        ['session', 'list', '--help'],
        ['session', 'info', '--help'],
        ['session', 'attach', '--help'],
        ['session', 'prune', '--help'],
        ['session', 'rm', '--help'],
        ['cookies', '--help'],
        ['cookies', 'get', '--help'],
        ['cookies', 'set', '--help'],
        ['cookies', 'clear', '--help'],
        ['har', '--help'],
        ['har', 'record', '--help'],
        ['har', 'replay', '--help'],
        ['network', '--help'],
        ['network', 'logs', '--help'],
        ['cloudflare', '--help'],
        ['cloudflare', 'bypass', '--help'],
        ['cloudflare', 'auto-solve', '--help'],
        ['tabs', '--help'],
        ['tabs', 'list', '--help'],
        ['tabs', 'new', '--help'],
        ['tabs', 'close', '--help'],
        ['tabs', 'focus', '--help'],
        ['network', 'watch', '--help'],
        ['network', 'block', '--help'],
        ['network', 'mock', '--help'],
        ['network', 'inject-header', '--help'],
        ['network', 'fail', '--help'],
        ['wait', '--help'],
        ['scroll', '--help'],
        ['upload', '--help'],
        ['batch', '--help'],
        ['keyboard', '--help'],
        ['keyboard', 'press', '--help'],
        ['keyboard', 'hotkey', '--help'],
        ['keyboard', 'down', '--help'],
        ['keyboard', 'up', '--help'],
        ['keyboard', 'type', '--help'],
        ['mouse', '--help'],
        ['mouse', 'move', '--help'],
        ['mouse', 'click', '--help'],
        ['mouse', 'drag', '--help'],
        ['mouse', 'hover', '--help'],
    ],
)
def test_subcommand_help(cmd: list[str]):
    result = runner.invoke(app, cmd)
    assert result.exit_code == 0, f'`{" ".join(cmd)}` failed: {result.stdout}'
