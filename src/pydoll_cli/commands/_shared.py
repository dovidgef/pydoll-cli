"""Shared helpers for command modules."""

from __future__ import annotations

_URL_PREFIXES = ('http://', 'https://', 'file://', 'data:', 'about:', 'chrome://')


def looks_like_url(s: str | None) -> bool:
    return s is not None and s.startswith(_URL_PREFIXES)


def _normalize_url_selector(url: str | None, selector: str) -> tuple[str | None, str]:
    """For commands shaped ``URL SELECTOR`` (both positional).

    When attached via ``--session`` / ``--connect``, users naturally omit the URL
    and pass only a selector. Typer then assigns the selector to the URL slot
    and leaves SELECTOR empty. Auto-correct: if URL doesn't look like a URL
    and SELECTOR is empty, treat URL as the selector.
    """
    if url is not None and not looks_like_url(url) and not selector:
        return None, url
    return url, selector


def _normalize_url_selector_text(
    url: str | None, selector: str, text: str
) -> tuple[str | None, str, str]:
    """For commands shaped ``URL SELECTOR TEXT``.

    Shift args left when URL is actually the selector (not a real URL).
    """
    if url is not None and not looks_like_url(url) and selector and not text:
        return None, url, selector
    return url, selector, text
