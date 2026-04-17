"""Persistent-session manager.

A session is a detached browser process with remote debugging enabled. Its
metadata (pid, port, ws_url, user_data_dir) is persisted under the user's
cache dir so later CLI invocations can reconnect via `--session NAME`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import aiohttp
import psutil

from pydoll_cli import browsers
from pydoll_cli.context import GlobalOptions

_IS_WINDOWS = platform.system() == 'Windows'


# ---- Paths --------------------------------------------------------------


def cache_dir() -> Path:
    """Root cache directory for pydoll-cli session state."""
    if _IS_WINDOWS:
        base = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
        return Path(base) / 'pydoll-cli'
    base = os.environ.get('XDG_CACHE_HOME') or str(Path.home() / '.cache')
    return Path(base) / 'pydoll-cli'


def sessions_dir() -> Path:
    return cache_dir() / 'sessions'


def state_path(name: str) -> Path:
    return sessions_dir() / f'{name}.json'


def user_data_dir(name: str) -> Path:
    return sessions_dir() / name / 'user-data'


def log_path(name: str) -> Path:
    return sessions_dir() / name / 'browser.log'


# ---- State --------------------------------------------------------------


@dataclass
class SessionState:
    name: str
    pid: int
    port: int
    ws_url: str
    user_data_dir: str
    browser: str
    binary: str
    started_at: float

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_file(cls, path: Path) -> SessionState:
        data = json.loads(path.read_text())
        return cls(**data)


# ---- Liveness -----------------------------------------------------------


def _pid_alive(pid: int) -> bool:
    return psutil.pid_exists(pid)


async def _probe_ws(port: int, *, timeout: float = 1.0) -> str | None:
    url = f'http://127.0.0.1:{port}/json/version'
    try:
        async with (
            aiohttp.ClientSession() as s,
            s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r,
        ):
            if r.status != 200:
                return None
            data = await r.json()
            url_val = data.get('webSocketDebuggerUrl')
            return str(url_val) if url_val is not None else None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


async def alive(state: SessionState) -> bool:
    if not _pid_alive(state.pid):
        return False
    ws = await _probe_ws(state.port)
    return ws is not None


# ---- List / load --------------------------------------------------------


def list_states() -> list[SessionState]:
    d = sessions_dir()
    if not d.exists():
        return []
    out: list[SessionState] = []
    for p in sorted(d.glob('*.json')):
        try:
            out.append(SessionState.from_file(p))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return out


def load(name: str) -> SessionState:
    p = state_path(name)
    if not p.exists():
        raise FileNotFoundError(
            f'No session named {name!r}. Start one with `pydoll-cli session start {name}`.'
        )
    return SessionState.from_file(p)


# ---- Start / stop --------------------------------------------------------


async def start(
    name: str,
    opts: GlobalOptions,
    *,
    initial_url: str | None = None,
    startup_timeout: float = 30.0,
) -> SessionState:
    """Launch a detached browser process with remote-debugging enabled."""
    if state_path(name).exists():
        existing = load(name)
        if await alive(existing):
            return existing
        # Stale — clean up.
        stop_quiet(name)

    binary = _resolve_binary(opts)
    port = opts.cdp_port or _free_port()
    udir = _resolve_user_data_dir(name, opts)
    udir.mkdir(parents=True, exist_ok=True)
    log_path(name).parent.mkdir(parents=True, exist_ok=True)

    args = _build_launch_args(binary, port, udir, opts, initial_url)

    log_file = open(log_path(name), 'ab', buffering=0)  # noqa: SIM115 — FD handed to subprocess
    creationflags = 0
    start_new_session = False
    if _IS_WINDOWS:
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        start_new_session = True

    proc = subprocess.Popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=log_file,
        close_fds=True,
        start_new_session=start_new_session,
        creationflags=creationflags,
    )

    # Wait for /json/version to respond.
    ws_url = await _wait_for_ws(port, deadline=time.monotonic() + startup_timeout)
    if ws_url is None:
        proc.terminate()
        raise TimeoutError(
            f'Browser on port {port} did not respond within {startup_timeout}s. '
            f'See {log_path(name)} for browser output.'
        )

    state = SessionState(
        name=name,
        pid=proc.pid,
        port=port,
        ws_url=ws_url,
        user_data_dir=str(udir),
        browser=opts.browser,
        binary=str(binary),
        started_at=time.time(),
    )
    state_path(name).parent.mkdir(parents=True, exist_ok=True)
    state_path(name).write_text(state.to_json())
    return state


def stop_quiet(name: str) -> None:
    """Best-effort stop: kill the pid if alive, remove state file."""
    try:
        state = load(name)
    except FileNotFoundError:
        return
    _kill(state.pid)
    with contextlib.suppress(FileNotFoundError):
        state_path(name).unlink()


def stop(name: str, *, timeout: float = 10.0) -> None:
    """Orderly stop: SIGTERM, wait, SIGKILL on timeout, remove state file."""
    state = load(name)
    _kill(state.pid, timeout=timeout)
    state_path(name).unlink(missing_ok=True)


def _kill(pid: int, *, timeout: float = 10.0) -> None:
    if not _pid_alive(pid):
        return
    try:
        if _IS_WINDOWS:
            subprocess.run(['taskkill', '/PID', str(pid), '/T'], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return
    deadline = time.monotonic() + timeout
    while _pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            if _IS_WINDOWS:
                subprocess.run(
                    ['taskkill', '/F', '/PID', str(pid), '/T'], check=False, capture_output=True
                )
            else:
                os.kill(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass


# ---- Internals ----------------------------------------------------------


def _resolve_binary(opts: GlobalOptions) -> Path:
    if opts.browser_binary is not None:
        p = Path(opts.browser_binary)
        if not p.is_file():
            raise FileNotFoundError(f'--browser-binary not found: {p}')
        return p
    return browsers.require(opts.browser)


def _resolve_user_data_dir(name: str, opts: GlobalOptions) -> Path:
    if opts.user_data_dir is not None:
        return Path(opts.user_data_dir)
    return user_data_dir(name)


def _build_launch_args(
    binary: Path,
    port: int,
    udir: Path,
    opts: GlobalOptions,
    initial_url: str | None,
) -> list[str]:
    args: list[str] = [
        str(binary),
        f'--remote-debugging-port={port}',
        f'--user-data-dir={udir}',
        '--no-first-run',
        '--no-default-browser-check',
    ]
    if opts.headless:
        args.append('--headless=new')
    if opts.incognito:
        args.append('--incognito')
    if opts.proxy:
        args.append(f'--proxy-server={opts.proxy}')
    if opts.user_agent:
        args.append(f'--user-agent={opts.user_agent}')
    if opts.window_size:
        w, _, h = opts.window_size.partition('x')
        if w and h:
            args.append(f'--window-size={w},{h}')
    if sys.platform == 'linux':
        # Harmless on most desktops; critical in containers.
        for flag in ('--no-sandbox', '--disable-dev-shm-usage'):
            if flag not in opts.extra_args:
                args.append(flag)
    for extra in opts.extra_args:
        if extra and extra not in args:
            args.append(extra)
    if initial_url:
        args.append(initial_url)
    return args


def _free_port() -> int:
    """Pick a free local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return int(s.getsockname()[1])


async def _wait_for_ws(port: int, *, deadline: float) -> str | None:
    while time.monotonic() < deadline:
        ws = await _probe_ws(port, timeout=0.75)
        if ws:
            return ws
        await asyncio.sleep(0.15)
    return None
