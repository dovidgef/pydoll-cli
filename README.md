# pydoll-cli

A command-line wrapper around [pydoll](https://github.com/autoscrape-labs/pydoll) — automate Chromium-based browsers (Chrome, Edge, Wavebox, any Chromium) over the Chrome DevTools Protocol with no WebDriver, stealth defaults, and first-class JSON output for AI agents.

## Install

```bash
# Recommended: isolated, upgradable tool install (Astral uv)
uv tool install pydoll-cli

# Alternatives
pipx install pydoll-cli
pip install pydoll-cli
```

After install both commands are on your PATH:

```bash
pydoll-cli --help
pydoll --help            # alias
```

Python 3.10+ is required. Google Chrome (or Edge / Wavebox / Chromium) must be installed locally; pydoll-cli auto-detects standard install paths on Linux, macOS, and Windows, or you can pass `--browser-binary /path/to/chrome`.

## Quick start

```bash
# One-shot screenshot
pydoll-cli screenshot https://example.com -o shot.png

# Print rendered page title as JSON
pydoll-cli --output json get https://example.com

# Persistent session (fast for multi-step flows / AI agents)
pydoll-cli session start agent-run --no-headless
pydoll-cli --session agent-run get https://news.ycombinator.com
pydoll-cli --session agent-run query "a.storylink" --all --attr href --output json
pydoll-cli session stop agent-run

# Attach to a running Chrome/Wavebox and operate in an isolated incognito tab
# that persists across commands (default for --browser wavebox; opt-in elsewhere)
pydoll-cli session start my-work --attach --url https://example.com
pydoll-cli --session my-work query "h1" --attr textContent
pydoll-cli session stop my-work    # deletes just the incognito context

# Attach but share your real logged-in profile (cookies/logins flow through)
# — session stop only closes the pinned tab; the browser keeps running
pydoll-cli session start linkedin --attach --share-profile \
  --url https://www.linkedin.com/feed/
pydoll-cli --session linkedin query "h1"

# Use Wavebox instead of Chrome
pydoll-cli --browser wavebox screenshot https://example.com -o shot.png

# Attach to an already-running Chrome/Wavebox (with --remote-debugging-port=9222)
# and drive a fresh incognito tab without disturbing the user's existing work
pydoll-cli --connect ws://127.0.0.1:9222/devtools/browser/XXX --fresh get https://example.com

# Bypass Cloudflare Turnstile and dump the page HTML
pydoll-cli cloudflare bypass https://example-protected.com -o page.html

# Structured extraction with a JSON schema
pydoll-cli extract https://quotes.toscrape.com \
  --schema examples/quotes.json --scope ".quote" --all

# Hybrid HTTP (authenticated via the browser session)
pydoll-cli --session logged-in request GET https://my-site.com/api/user/profile
```

## Feature overview

pydoll-cli exposes the full pydoll feature set as subcommands. See `pydoll-cli <command> --help` for examples.

| Category            | Commands                                                                 |
| ------------------- | ------------------------------------------------------------------------ |
| Navigation          | `get`, `source`, `text`                                                  |
| Capture             | `screenshot`, `pdf`, `bundle`                                            |
| Interaction         | `click`, `type`, `eval`, `query`                                         |
| Extraction          | `extract` (Pydantic schema — Python file or JSON)                        |
| Network             | `request`, `har record`, `har replay`, `network logs`                    |
| Cookies & state     | `cookies get`, `cookies set`, `cookies clear`                            |
| Stealth / evasion   | `cloudflare bypass`, humanized typing via `type --human`                 |
| Sessions            | `session start`, `session stop`, `session list`, `session info`, `session attach` |
| Scripting           | `shell`, `run SCRIPT.py`                                                 |
| Introspection       | `info`, `browsers`                                                       |

## Global options (available on every subcommand)

| Flag                           | Meaning                                                                   |
| ------------------------------ | ------------------------------------------------------------------------- |
| `--browser {chrome,edge,wavebox,chromium}` | Which browser (default `chrome`).                               |
| `--browser-binary PATH`        | Custom executable path. Overrides `--browser` detection.                  |
| `--headless / --no-headless`   | Default `--headless`.                                                     |
| `--user-data-dir PATH`         | Persistent profile directory.                                             |
| `--incognito`                  | Launch incognito.                                                         |
| `--proxy URL`                  | `scheme://user:pass@host:port`. Credentials handled automatically.        |
| `--user-agent STRING`          | Override UA (Client Hints + navigator auto-synced).                       |
| `--accept-languages CSV`       | e.g. `en-US,en`.                                                          |
| `--window-size WxH`            | e.g. `1920x1080`.                                                         |
| `--disable-images`             | Skip image loading.                                                       |
| `-a, --arg TEXT`               | Repeatable raw Chromium flag, e.g. `-a --no-sandbox`.                     |
| `--pref KEY=VAL`               | Repeatable nested preference, `profile.password_manager_enabled=false`.   |
| `--cdp-port PORT`              | Fix the remote-debugging port (default: random).                          |
| `--connect WS_URL`             | Attach to a running browser's WebSocket endpoint; don't launch one.       |
| `--session NAME`               | Reuse a persistent session (see `session start`).                         |
| `--tab INT` / `--tab-url URL`  | Target a specific tab when using `--session` / `--connect`.               |
| `--new-tab`                    | With `--connect`/`--session`: open a new tab (default context).           |
| `--fresh`                      | With `--connect`/`--session`: open a new incognito context + tab; leaves existing tabs untouched. Ideal for driving your logged-in browser without disturbing it. |

Session-start-only flags (on `session start`):

| Flag                      | Meaning                                                                                                                              |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `--attach/--no-attach`    | Attach to a running browser on `--attach-port` (default 9222) instead of launching one. On by default for `--browser wavebox`.        |
| `--attach-port PORT`      | CDP port of the running browser to attach to (default 9222).                                                                          |
| `--share-profile`         | With `--attach`: pin a tab in the running browser's default (logged-in) context instead of a fresh incognito context. `session stop` then just closes the tab. |
| `--url URL`               | Navigate the pinned tab to this URL on startup.                                                                                       |
| `--startup-timeout SEC`   | Seconds to wait for CDP readiness on a fresh launch (default 30).                                                                     |
| `--timeout SECONDS`            | Per-command timeout (default 30).                                         |
| `--output {text,json}`         | `json` for stable machine-readable output.                                |
| `-q, --quiet`                  | Suppress non-data output.                                                 |
| `--log-level LEVEL`            | Python logging level (forwarded to pydoll).                               |
| `--log-file PATH`              | Write pydoll logs to a file.                                              |

## Exit codes

| Code | Meaning                    |
| ---- | -------------------------- |
| 0    | Success                    |
| 1    | Generic failure            |
| 2    | CLI argument error (typer) |
| 3    | Operation timed out        |
| 4    | Element not found          |
| 5    | Browser launch failed      |
| 6    | Session not running        |
| 130  | Interrupted (Ctrl-C)       |

## Use with AI agents (Claude Code, etc.)

See [AGENTS.md](AGENTS.md) for patterns, the stable JSON contract, and recommended workflows for letting an agent drive a persistent browser session across multiple tool invocations.

## Development

```bash
git clone https://github.com/dovidgefen/pydoll-cli && cd pydoll-cli
uv sync
uv run pydoll-cli --help
uv run pytest
uv run ruff check .
```

## License

MIT — see [LICENSE](LICENSE). Uses [pydoll](https://github.com/autoscrape-labs/pydoll) (MIT).
