"""Target/tab filtering shared by every place the CLI picks or lists a tab.

pydoll's ``get_opened_tabs`` keeps any target whose ``type`` is ``page`` and
whose URL doesn't contain ``extension``. That lets browser-internal targets —
most importantly a detached DevTools window (``devtools://…``) — show up as a
regular tab and, worse, land at index 0 so ``--session NAME`` without
``--tab-url`` drives DevTools instead of the app.

This module is deliberately dependency-free with respect to ``async_runner``,
``session``, and ``commands.tabs``: those three all need it, and two of them
import each other, so anything shared has to live outside all of them.
"""

from __future__ import annotations

from typing import Any

INTERNAL_SCHEMES = ('devtools://', 'chrome://')


def is_internal_url(url: str | None) -> bool:
    """True for browser-internal targets that should never be auto-selected."""
    return url is not None and url.startswith(INTERNAL_SCHEMES)


async def visible_tabs(browser: Any, *, include_internal: bool = False) -> list[Any]:
    """Open tabs, minus browser-internal ones.

    Every list-of-tabs consumer routes through here so ``tabs list`` indices
    stay in sync with what ``--tab N`` resolves to. Tabs whose ``current_url``
    raises (detached target, broken connection) are skipped, matching the
    tolerance in ``session._find_tab_matching``.
    """
    tabs = await browser.get_opened_tabs()
    if include_internal:
        return list(tabs)
    out: list[Any] = []
    for tab in tabs:
        try:
            url = await tab.current_url
        except Exception:
            continue
        if not is_internal_url(url):
            out.append(tab)
    return out
