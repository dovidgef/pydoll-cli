"""Detect installed Chromium-based browsers on this system.

Pydoll handles Chrome/Edge detection internally; we extend detection to
Wavebox and generic Chromium, and provide a unified lookup that returns an
explicit binary path ready to pass into `ChromiumOptions.binary_location`.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserCandidate:
    """A detected browser installation."""

    kind: str  # chrome | edge | wavebox | chromium
    path: Path
    display_name: str


# Standard install locations per OS. Ordered: first hit wins.
_PATHS: dict[str, dict[str, list[str]]] = {
    'Linux': {
        'chrome': [
            '/usr/bin/google-chrome',
            '/usr/bin/google-chrome-stable',
            '/opt/google/chrome/google-chrome',
            '/snap/bin/google-chrome',
        ],
        'edge': [
            '/usr/bin/microsoft-edge',
            '/usr/bin/microsoft-edge-stable',
            '/opt/microsoft/msedge/msedge',
        ],
        'wavebox': [
            '/usr/bin/wavebox',
            '/opt/wavebox/wavebox',
            '/opt/wavebox.io/wavebox/wavebox',
            '/opt/wavebox/latest/wavebox',
            '~/.local/share/wavebox/wavebox',
        ],
        'chromium': [
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            '/snap/bin/chromium',
        ],
    },
    'Darwin': {
        'chrome': [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        ],
        'edge': [
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        ],
        'wavebox': [
            '/Applications/Wavebox.app/Contents/MacOS/Wavebox',
        ],
        'chromium': [
            '/Applications/Chromium.app/Contents/MacOS/Chromium',
        ],
    },
    'Windows': {
        'chrome': [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        ],
        'edge': [
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        ],
        'wavebox': [
            r'C:\Program Files\WBD\Wavebox\Wavebox.exe',
            r'%LOCALAPPDATA%\WBD\Wavebox\Wavebox.exe',
        ],
        'chromium': [
            r'C:\Program Files\Chromium\Application\chrome.exe',
        ],
    },
}

# Additional PATH lookups as a last-resort fallback.
_PATH_CMDS: dict[str, list[str]] = {
    'chrome': ['google-chrome', 'google-chrome-stable', 'chrome'],
    'edge': ['microsoft-edge', 'microsoft-edge-stable', 'msedge'],
    'wavebox': ['wavebox'],
    'chromium': ['chromium', 'chromium-browser'],
}

_DISPLAY_NAMES = {
    'chrome': 'Google Chrome',
    'edge': 'Microsoft Edge',
    'wavebox': 'Wavebox',
    'chromium': 'Chromium',
}


def _expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))


def find(kind: str) -> Path | None:
    """Locate a single browser binary by kind. Returns None if not found."""
    os_name = platform.system()
    for candidate in _PATHS.get(os_name, {}).get(kind, []):
        p = _expand(candidate)
        if p.is_file():
            return p
    for cmd in _PATH_CMDS.get(kind, []):
        which = shutil.which(cmd)
        if which:
            return Path(which)
    return None


def require(kind: str) -> Path:
    """Locate a browser or raise a user-friendly error."""
    p = find(kind)
    if p is None:
        raise FileNotFoundError(
            f'Could not find {_DISPLAY_NAMES.get(kind, kind)} on this system. '
            f'Pass --browser-binary /path/to/executable to override detection.'
        )
    return p


def detect_all() -> list[BrowserCandidate]:
    """Return every browser installation detected on this system."""
    candidates: list[BrowserCandidate] = []
    seen: set[Path] = set()
    for kind in ('chrome', 'edge', 'wavebox', 'chromium'):
        p = find(kind)
        if p is not None and p not in seen:
            seen.add(p)
            candidates.append(
                BrowserCandidate(kind=kind, path=p, display_name=_DISPLAY_NAMES[kind])
            )
    return candidates
