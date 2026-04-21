"""Translate CLI global options into a pydoll ChromiumOptions instance."""

from __future__ import annotations

from pydoll.browser.options import ChromiumOptions

from pydoll_cli import browsers
from pydoll_cli.context import GlobalOptions


def build_options(opts: GlobalOptions) -> ChromiumOptions:
    """Build a configured `ChromiumOptions` from `GlobalOptions`."""
    options = ChromiumOptions()

    # Binary resolution: explicit path > browser kind lookup.
    if opts.browser_binary is not None:
        options.binary_location = str(opts.browser_binary)
    elif opts.browser in ('wavebox', 'chromium'):
        # Pydoll only knows chrome/edge; for Wavebox/Chromium we resolve manually.
        options.binary_location = str(browsers.require(opts.browser))

    options.headless = opts.headless

    if opts.user_data_dir is not None:
        options.add_argument(f'--user-data-dir={opts.user_data_dir}')
    if opts.incognito:
        options.add_argument('--incognito')
    if opts.proxy:
        options.add_argument(f'--proxy-server={opts.proxy}')
    if opts.user_agent:
        options.add_argument(f'--user-agent={opts.user_agent}')
    if opts.accept_languages:
        options.set_accept_languages(opts.accept_languages)
    if opts.window_size:
        w, _, h = opts.window_size.partition('x')
        if w and h:
            options.add_argument(f'--window-size={w},{h}')
    merged_prefs: dict[str, object] = {}
    if opts.disable_images:
        # Prefer the preference over a command-line flag; equivalent and stable.
        _deep_merge(
            merged_prefs,
            {'profile': {'managed_default_content_settings': {'images': 2}}},
        )

    if opts.in_container:
        # Docker/CI: sandbox can't init and /dev/shm is tiny. Opt-in only.
        for flag in ('--no-sandbox', '--disable-dev-shm-usage'):
            if flag not in options.arguments:
                options.add_argument(flag)

    for raw in opts.extra_args:
        if raw and raw not in options.arguments:
            options.add_argument(raw)

    for pref in opts.prefs:
        key, _, value = pref.partition('=')
        if not key or not _:
            raise ValueError(f'--pref expects KEY=VALUE, got: {pref!r}')
        _deep_merge(merged_prefs, _dotted_to_nested(key, _parse_scalar(value)))

    if merged_prefs:
        # Assign once so pydoll's shallow top-level merge doesn't drop branches.
        options.browser_preferences = merged_prefs

    return options


def _deep_merge(base: dict[str, object], new: dict[str, object]) -> None:
    """In-place recursive merge: ``new`` is layered onto ``base``."""
    for k, v in new.items():
        existing = base.get(k)
        if isinstance(existing, dict) and isinstance(v, dict):
            _deep_merge(existing, v)
        else:
            base[k] = v


def _parse_scalar(v: str) -> object:
    """Parse a scalar value from a KEY=VAL flag."""
    low = v.lower()
    if low in ('true', 'false'):
        return low == 'true'
    if low in ('null', 'none'):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _dotted_to_nested(dotted_key: str, value: object) -> dict[str, object]:
    """Convert 'a.b.c' + value into {'a': {'b': {'c': value}}}."""
    parts = dotted_key.split('.')
    out: dict[str, object] = {}
    cur: dict[str, object] = out
    for part in parts[:-1]:
        nxt: dict[str, object] = {}
        cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value
    return out
