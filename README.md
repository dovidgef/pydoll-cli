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

# Persistent session (fast for multi-step flows / AI agents).
# `--no-headless` is a *global* flag — it must come BEFORE the subcommand.
pydoll-cli --no-headless session start agent-run
pydoll-cli --session agent-run get https://news.ycombinator.com
pydoll-cli --output json --session agent-run query "a.storylink" --all --attr href
pydoll-cli session stop agent-run            # kills the browser AND deletes its profile (--no-purge to keep)

# Reclaim disk from leftover/old session profiles (they show as "orphan" in list).
pydoll-cli session prune --orphans --dry-run # preview; add --yes to delete. Also --dead, --older-than N
pydoll-cli session rm agent-run              # stop if running + delete one session outright

# Attach to a running Chrome/Wavebox and operate in an isolated incognito tab
# that persists across commands (default for --browser wavebox; opt-in elsewhere)
pydoll-cli session start my-work --attach --url https://example.com
pydoll-cli --session my-work query "h1" --attr textContent
pydoll-cli session stop my-work    # deletes just the incognito context

# Attach but share your real logged-in profile (cookies/logins flow through).
# If --url is already open in another tab, that tab is adopted as-is.
# session stop leaves the pinned tab open by default (--close-tab to close it).
pydoll-cli session start linkedin --attach --share-profile \
  --url https://www.linkedin.com/feed/
pydoll-cli --session linkedin query "h1"

# Or: ride along on a tab the user already has open (adopt-only, never spawns).
pydoll-cli --browser wavebox session start work --share-profile \
  --tab-url 'github.com/anthropics'

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

# SPA-friendly: load fast, then wait on real content
pydoll-cli --page-load-state interactive --session s get https://app.example.com
pydoll-cli --session s wait --selector ".content" --wait 30
pydoll-cli --session s query "h1"

# Aggregator with progressive results — wait for the result set to stabilize
pydoll-cli --session s wait --stable-ids ".result|data-id" --stable-ms 2000 --wait 35

# Many independent URLs in parallel (one tab each, ~10× sequential)
pydoll-cli --output json batch https://a.com https://b.com https://c.com \
  --query "h1" --concurrency 3

# Network interception (wrap pattern): block heavy assets for one screenshot
pydoll-cli --session s network block -t Image -t Stylesheet -t Font \
  -- screenshot https://heavy-site.com -o shot.png

# Mock an internal API while driving the page
pydoll-cli --session s network mock -p /api/me --status 200 --body fixture.json \
  -- get https://app.com
```

## Feature overview

pydoll-cli exposes the full pydoll feature set as subcommands. See `pydoll-cli <command> --help` for examples.

| Category            | Commands                                                                 |
| ------------------- | ------------------------------------------------------------------------ |
| Navigation          | `get [URL] --wait-for SEL`, `source`, `text`                             |
| Capture             | `screenshot`, `pdf`, `bundle`                                            |
| Interaction         | `click`, `type`, `eval`, `query`, `keyboard`, `mouse`, `scroll`, `upload`|
| SPA waits           | `wait --selector\|--network-idle\|--url-contains\|--page-event\|--js\|--stable-ids` |
| Parallel            | `batch URL [URL...]` (asyncio.gather across tabs)                        |
| Extraction          | `extract` (Pydantic schema — Python file or JSON)                        |
| Network             | `request`, `har record`, `har replay`, `network logs`, `network watch`   |
| Interception        | `network block`, `network mock`, `network inject-header`, `network fail` (Fetch wrap pattern) |
| Cookies & state     | `cookies get`, `cookies set`, `cookies clear`                            |
| Stealth / evasion   | `cloudflare bypass`, `cloudflare auto-solve`, humanized typing/clicking, `--webrtc-leak-protection` |
| Sessions            | `session start`, `session stop`, `session list`, `session info`, `session attach`, `session prune`, `session rm` |
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
| `--proxy-insecure`             | Append `--ignore-certificate-errors`. For authenticated proxies (Bright Data, etc.) that present an internal CA cert. |
| `--webrtc-leak-protection`     | Enable pydoll WebRTC leak protection (recommended when proxying — WebRTC otherwise reveals the real IP). |
| `--page-load-state {complete,interactive}` | When to consider navigation complete. `interactive` returns on DOMContentLoaded (~2–5× faster on JS-heavy pages); `complete` (default) waits for full `load`. |
| `--user-agent STRING`          | Override UA (Client Hints + navigator auto-synced).                       |
| `--accept-languages CSV`       | e.g. `en-US,en`.                                                          |
| `--window-size WxH`            | e.g. `1920x1080`.                                                         |
| `--disable-images`             | Skip image loading.                                                       |
| `--in-container`               | Docker/CI-only: add `--no-sandbox` + `--disable-dev-shm-usage`. Skip on a normal desktop — the Chrome sandbox should stay on. |
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
| `--share-profile`         | With `--attach`: pin a tab in the running browser's default (logged-in) context instead of a fresh incognito context. `session stop` then leaves the pinned tab open by default (use `--close-tab` to close it). |
| `--url URL`               | Navigate the pinned tab to this URL on startup. With `--share-profile`: if a tab matching this URL is already open, it's adopted as-is (no duplicate, no re-navigation). |
| `--tab-url SUBSTR`        | With `--share-profile` only: **adopt-only.** Pin an already-open tab whose URL contains `SUBSTR`. Errors with exit 4 if no match. Mutually exclusive with `--url`. |
| `--startup-timeout SEC`   | Seconds to wait for CDP readiness on a fresh launch (default 30).                                                                     |
| `--timeout SECONDS`            | Per-command timeout (default 30).                                         |
| `--output {text,json}`         | `json` for stable machine-readable output.                                |
| `-q, --quiet`                  | Suppress non-data output.                                                 |
| `--log-level LEVEL`            | Python logging level (forwarded to pydoll).                               |
| `--log-file PATH`              | Write pydoll logs to a file.                                              |

## Exit codes

| Code | Meaning                          |
| ---- | -------------------------------- |
| 0    | Success                          |
| 1    | Generic failure                  |
| 2    | CLI argument error (typer)       |
| 3    | Operation timed out              |
| 4    | Element not found                |
| 5    | Browser launch failed            |
| 6    | Session not running              |
| 7    | JavaScript exception in `eval`   |
| 130  | Interrupted (Ctrl-C)             |

## Use with AI agents (Claude Code, etc.)

See [AGENTS.md](AGENTS.md) for patterns, the stable JSON contract, and recommended workflows for letting an agent drive a persistent browser session across multiple tool invocations.

### Claude Code skill

This repo ships a [Claude Code skill](https://code.claude.com/docs/en/skills) at [`.claude/skills/pydoll-cli/SKILL.md`](.claude/skills/pydoll-cli/SKILL.md). It teaches Claude the canonical session-based workflow, the stable JSON contract, and the real gotchas that trip up naive agents (tab-index instability, `get` reusing the current tab, `extract --schema` field syntax, etc.). Kept lean (~180 lines) so it only pays context when triggered.

Inside this repo it auto-loads at project scope with no action needed. To install it elsewhere, use the bundled command (works the same for `pip` / `uv tool` / `pipx` installs — the skill ships inside the wheel):

```bash
# Default: project scope — install into the current repo (.claude/skills/pydoll-cli/SKILL.md).
# Run this from any project root to make the skill available in that repo only.
pydoll-cli install-skill

# User scope — make it available in every Claude Code session on your machine.
pydoll-cli install-skill --scope user      # → ~/.claude/skills/pydoll-cli/SKILL.md

# Custom location.
pydoll-cli install-skill --target ./.claude/skills

# Overwrite an older copy.
pydoll-cli install-skill --force
```

Claude Code follows the same scope hierarchy for skills as it does for plugins/settings — see Anthropic's [skills](https://docs.claude.com/en/docs/claude-code/skills) and [plugins](https://docs.claude.com/en/docs/claude-code/plugins) docs. (For a single SKILL.md like this one, a plain skill is the right packaging; the plugin format is for bundles of skills + agents + hooks.)

Repo-clone alternatives (track in-repo edits, no reinstall needed):

```bash
# Symlink (edits/upgrades flow through automatically)
mkdir -p ~/.claude/skills
ln -s "$(pwd)/.claude/skills/pydoll-cli" ~/.claude/skills/pydoll-cli

# Or copy (independent snapshot; update manually on upgrades)
cp -r .claude/skills/pydoll-cli ~/.claude/skills/pydoll-cli
```

Verify: start Claude Code and ask *"what skills are available?"* — `pydoll-cli` should be listed. Or run `/pydoll-cli` to invoke it directly.

The skill complements `AGENTS.md`: the skill is the compact in-context primer (always available, trigger-aware), `AGENTS.md` is the deep reference (only read when needed). The skill points at `AGENTS.md` for the long tail.

## Development

```bash
git clone https://github.com/dovidgefen/pydoll-cli && cd pydoll-cli
uv sync --group dev
uv run pre-commit install   # runs ruff format, ruff check, mypy, pytest on each commit
uv run pydoll-cli --help
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Pre-commit mirrors the GitHub Actions CI checks (`.pre-commit-config.yaml`),
so a passing local commit means a passing CI run.

## License

MIT — see [LICENSE](LICENSE). Uses [pydoll](https://github.com/autoscrape-labs/pydoll) (MIT).
