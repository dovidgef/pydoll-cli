"""Output formatting (text vs JSON), logging, and exit-code helpers.

`--output json` emits a single JSON document to stdout; human-readable text is
the default. Logs and progress always go to stderr so stdout stays parseable.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, TextIO

import typer
from rich.console import Console

from pydoll_cli.context import GlobalOptions

# ---- Exit codes ---------------------------------------------------------

EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_BAD_ARGS = 2
EXIT_TIMEOUT = 3
EXIT_NOT_FOUND = 4
EXIT_BROWSER_LAUNCH = 5
EXIT_NO_SESSION = 6
EXIT_INTERRUPTED = 130


class CliError(Exception):
    """Raised by commands to trigger an orderly, coded exit."""

    def __init__(self, message: str, exit_code: int = EXIT_GENERIC) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# ---- Logging ------------------------------------------------------------


def configure_logging(opts: GlobalOptions) -> None:
    """Configure stdlib logging based on flags. Logs always go to stderr."""
    level_name = 'ERROR' if opts.quiet else opts.log_level.upper()
    level = getattr(logging, level_name, logging.WARNING)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if opts.log_file is not None:
        handlers.append(logging.FileHandler(opts.log_file))

    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=handlers,
        force=True,
    )


# ---- Printer ------------------------------------------------------------


class Printer:
    """Central output sink. Respects `--output` and `--quiet`."""

    def __init__(self, opts: GlobalOptions, *, stdout: TextIO | None = None) -> None:
        self.opts = opts
        self._stdout = stdout or sys.stdout
        self._stderr_console = Console(stderr=True, highlight=False, soft_wrap=True)

    # ---- data (stdout) --------------------------------------------------

    def emit(self, data: Any, *, text: str | None = None) -> None:
        """Emit primary command output.

        In JSON mode, `data` is serialized to stdout as JSON.
        In text mode, `text` (or `data` stringified) is printed to stdout.
        """
        if self.opts.output == 'json':
            json.dump(data, self._stdout, default=_json_default, ensure_ascii=False)
            self._stdout.write('\n')
            self._stdout.flush()
        else:
            if text is None:
                text = _default_text(data)
            if text:
                print(text, file=self._stdout)
                self._stdout.flush()

    def emit_path(self, path: Path, *, extra: dict[str, Any] | None = None) -> None:
        """Convenience for commands that produce a file."""
        payload: dict[str, Any] = {'path': str(path)}
        if extra:
            payload.update(extra)
        self.emit(payload, text=str(path))

    # ---- messages (stderr) ---------------------------------------------

    def info(self, msg: str) -> None:
        if not self.opts.quiet:
            self._stderr_console.print(msg, style='dim')

    def warn(self, msg: str) -> None:
        if not self.opts.quiet:
            self._stderr_console.print(f'[yellow]warning:[/] {msg}')

    def error(self, msg: str) -> None:
        self._stderr_console.print(f'[red]error:[/] {msg}')

    # ---- convenience ----------------------------------------------------

    def fatal(self, msg: str, exit_code: int = EXIT_GENERIC) -> typer.Exit:
        """Print an error to stderr and return a typer.Exit to raise."""
        self.error(msg)
        return typer.Exit(exit_code)


def _default_text(data: Any) -> str:
    """Reasonable stringification for mixed return types."""
    if data is None:
        return ''
    if isinstance(data, (str, int, float, bool)):
        return str(data)
    if isinstance(data, dict):
        # "key: value" one-per-line; skip None values
        return '\n'.join(f'{k}: {v}' for k, v in data.items() if v is not None)
    if isinstance(data, list):
        return '\n'.join(_default_text(x) for x in data)
    return json.dumps(data, default=_json_default, ensure_ascii=False)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()
    if hasattr(obj, '__dict__'):
        return obj.__dict__
    return str(obj)
