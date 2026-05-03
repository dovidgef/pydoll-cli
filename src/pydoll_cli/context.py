"""Global CLI context passed between the root callback and each subcommand."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OutputFormat = Literal['text', 'json']
BrowserKind = Literal['chrome', 'edge', 'wavebox', 'chromium']


@dataclass
class GlobalOptions:
    """All root-level CLI flags, resolved once in the root callback."""

    # Browser selection
    browser: BrowserKind = 'chrome'
    browser_binary: Path | None = None
    headless: bool = True
    user_data_dir: Path | None = None
    incognito: bool = False
    proxy: str | None = None
    proxy_insecure: bool = False  # Adds --ignore-certificate-errors for authenticated proxies.
    user_agent: str | None = None
    accept_languages: str | None = None
    window_size: str | None = None
    disable_images: bool = False
    extra_args: list[str] = field(default_factory=list)
    prefs: list[str] = field(default_factory=list)
    cdp_port: int | None = None
    in_container: bool = False  # adds --no-sandbox + --disable-dev-shm-usage

    # Connection modes (mutually exclusive with fresh launch)
    connect: str | None = None
    session: str | None = None
    tab: int | None = None
    tab_url: str | None = None
    new_tab: bool = False  # With --connect/--session: open a new tab (default context)
    fresh: bool = False  # With --connect/--session: new incognito browser context + new tab

    # Behavior
    timeout: float = 30.0
    output: OutputFormat = 'text'
    quiet: bool = False
    log_level: str = 'WARNING'
    log_file: Path | None = None
