"""Target/tab filtering shared by every place the CLI picks or lists a tab.

pydoll's ``get_opened_tabs`` keeps any target whose ``type`` is ``page`` and
whose URL doesn't contain ``extension``. That lets browser-internal targets —
most importantly a detached DevTools window (``devtools://…``) — show up as a
regular tab and, worse, land at index 0 so ``--session NAME`` without
``--tab-url`` drives DevTools instead of the app.

URLs and titles come from ``Target.getTargets``, never from ``tab.current_url``
/ ``tab.title``. Those properties evaluate JavaScript *inside the page*, which
never returns once the renderer has been discarded — every browser that sleeps
background tabs (Wavebox, Edge, Chrome's Memory Saver) leaves such a target
attachable but dead. Reading URLs that way made enumeration stall for the full
per-command timeout on each sleeping tab, sequentially, before it could reach
the live one; a browser with a dozen slept tabs took over ten minutes to answer
``tabs list``. ``TargetInfo`` already carries both fields, so one browser-level
call replaces N renderer round-trips.

This module is deliberately dependency-free with respect to ``async_runner``,
``session``, and ``commands.tabs``: those three all need it, and two of them
import each other, so anything shared has to live outside all of them.
"""

from __future__ import annotations

import asyncio
from typing import Any

INTERNAL_SCHEMES = ('devtools://', 'chrome://')

#: Cap on the in-page fallback used only for a target ``Target.getTargets``
#: didn't report. Bounded so one dead renderer can't hang the whole command.
URL_PROBE_TIMEOUT = 5.0


def is_internal_url(url: str | None) -> bool:
    """True for browser-internal targets that should never be auto-selected."""
    return url is not None and url.startswith(INTERNAL_SCHEMES)


async def target_info_map(browser: Any) -> dict[str, dict[str, Any]]:
    """``targetId`` -> CDP ``TargetInfo``, in a single browser-level call.

    Never touches a renderer, so sleeping tabs cost nothing.
    """
    try:
        targets = await browser.get_targets()
    except Exception:
        return {}
    return {t['targetId']: t for t in targets if isinstance(t, dict) and t.get('targetId')}


def _info_for(info_map: dict[str, dict[str, Any]] | None, tab: Any) -> dict[str, Any] | None:
    return (info_map or {}).get(getattr(tab, '_target_id', None) or '')


async def _field(
    tab: Any,
    info_map: dict[str, dict[str, Any]] | None,
    key: str,
    prop: str,
    timeout: float,
) -> str | None:
    """``TargetInfo[key]`` if known, else a time-boxed read of ``tab.<prop>``."""
    info = _info_for(info_map, tab)
    if info is not None and info.get(key) is not None:
        return info[key]
    try:
        return await asyncio.wait_for(getattr(tab, prop), timeout)
    except Exception:
        return None


async def tab_url(
    tab: Any,
    info_map: dict[str, dict[str, Any]] | None = None,
    *,
    timeout: float = URL_PROBE_TIMEOUT,
) -> str | None:
    """URL of ``tab``, preferring ``TargetInfo`` over an in-page evaluate."""
    return await _field(tab, info_map, 'url', 'current_url', timeout)


async def tab_title(
    tab: Any,
    info_map: dict[str, dict[str, Any]] | None = None,
    *,
    timeout: float = URL_PROBE_TIMEOUT,
) -> str | None:
    """Title of ``tab``, preferring ``TargetInfo`` over an in-page evaluate."""
    return await _field(tab, info_map, 'title', 'title', timeout)


async def visible_tabs_with_urls(
    browser: Any, *, include_internal: bool = False
) -> list[tuple[Any, str | None]]:
    """``(tab, url)`` pairs for open tabs, minus browser-internal ones.

    Callers that need the URLs get them for free — re-reading them per tab is
    what used to make selection cost one timeout per sleeping tab.

    A tab whose URL resolves nowhere (detached target, broken connection) is
    dropped: it can't be matched by ``--tab-url`` and shouldn't silently absorb
    a ``--tab N`` index. Sleeping tabs are *not* in that category — CDP still
    reports their URL, so they stay listed and selectable.
    """
    tabs = await browser.get_opened_tabs()
    info_map = await target_info_map(browser)
    out: list[tuple[Any, str | None]] = []
    for tab in tabs:
        url = await tab_url(tab, info_map)
        if url is None:
            continue
        if include_internal or not is_internal_url(url):
            out.append((tab, url))
    return out


async def visible_tabs(browser: Any, *, include_internal: bool = False) -> list[Any]:
    """Open tabs, minus browser-internal ones.

    Every list-of-tabs consumer routes through here so ``tabs list`` indices
    stay in sync with what ``--tab N`` resolves to.
    """
    pairs = await visible_tabs_with_urls(browser, include_internal=include_internal)
    return [tab for tab, _ in pairs]
