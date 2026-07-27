# Using pydoll-cli with AI agents

pydoll-cli is designed so that an AI agent (Claude Code and similar) can drive
a Chromium-based browser through a stable command-line interface with
predictable, machine-readable output.

## Guiding principles

1. **`--output json` is a stable contract.** Every subcommand prints a single
   JSON document to stdout in JSON mode. Breaking shape changes bump the major
   version.
2. **Stdout is data, stderr is commentary.** Logs, warnings, progress, and
   errors go to stderr. Parse stdout; ignore (or surface) stderr.
3. **Sessions are cheap.** Reuse a single detached browser across many
   invocations rather than launching a new Chrome per step.
4. **Exit codes mean something.** The code tells the agent *why* a call failed.
5. **No hidden interactivity.** Every command runs to completion or times out.
6. **Sandbox stays on by default.** In Docker/CI, pass `--in-container` to add
   `--no-sandbox` + `--disable-dev-shm-usage`; never add them by hand on a real
   desktop.

## Recommended agent workflow

```bash
# 1. Start a long-lived session at the beginning of the agent run.
pydoll-cli session start agent-run --no-headless --output json > /tmp/session.json
#   → {"name": "agent-run", "pid": 31234, "port": 41721,
#      "ws_url": "ws://127.0.0.1:41721/devtools/browser/xyz",
#      "user_data_dir": "...", "browser": "chrome",
#      "binary": "/usr/bin/google-chrome", "started_at": 1713370000.42}

# 2. Drive it across many tool invocations.
pydoll-cli --session agent-run --output json get https://example.com
pydoll-cli --session agent-run --output json query "h1"
pydoll-cli --session agent-run --output json eval --script "return document.title"

# 3. Stop it at the end (important — detached process survives CLI exits).
pydoll-cli session stop agent-run
```

## Exit codes

| Code | Meaning                    | Agent should…                                               |
| ---- | -------------------------- | ----------------------------------------------------------- |
| 0    | Success                    | Proceed.                                                    |
| 1    | Generic failure            | Read stderr; retry or give up.                              |
| 2    | CLI argument error         | Fix flags/arguments.                                        |
| 3    | Operation timed out        | Retry with larger `--timeout`.                              |
| 4    | Element not found          | Re-check selector; retry with `--wait`.                     |
| 5    | Browser launch failed      | Check `--browser-binary` and system install.                |
| 6    | Session not running, or its pinned tab is gone | `pydoll-cli session start …` first. If the session exists but its tab was closed (or the browser restarted), re-pin with `--tab-url SUBSTR` or stop and start it again. |
| 7    | JS exception in `eval`     | Read the `JS error: …` line on stderr; fix the JS.          |
| 130  | Interrupted                | User cancelled.                                             |

## JSON output shapes (stable contract)

Each subcommand emits a JSON document with the shape below when run with
`--output json`.

### `get`
```json
{"url": "https://example.com", "title": "Example Domain"}
```

### `screenshot`, `pdf`, `bundle`
```json
{"path": "/tmp/shot.png"}
```
With `--base64`:
```json
{"base64": "<base64 payload>"}
```

### `source`
```json
{"html": "<!DOCTYPE html>…", "bytes": 4567}
```

### `text`
```json
{"text": "Example Domain\nThis domain is for use in…"}
```
With `--selector S --all`:
```json
{"texts": ["First", "Second", "Third"], "count": 3}
```

### `eval`
```json
{"value": "Example Domain"}
```
`value` preserves the JS return type: string, number, bool, list, or object.
Promises are awaited; on a JS exception the command exits **7** with `JS error: <description>` on stderr.

### `query`
Single element (default):
```json
{"text": "Example Domain", "attr": null, "tag": "h1"}
```
With `--all`:
```json
[
  {"text": "More information...", "attr": "https://www.iana.org/domains/example", "tag": "a"}
]
```

### `click`
```json
{"clicked": "a.more", "url": "https://example.com/more"}
```

### `type`
```json
{"selector": "input[name=q]", "typed": "pydoll"}
```

### `wait`
```json
{"ready": true, "ms": 1234, "matched": {"selector": ".content", "count": 1}}
```
`matched` shape varies by mode: `{selector,count}` for `--selector`/`--stable-ids`,
`{inflight,idle_ms}` for `--network-idle`, `{url}` for `--url-contains`,
`{event}` for `--page-event` (or `{event,already}` when `load`/`dom-content`
is already satisfied at call time — `document.readyState` pre-check),
`{value}` for `--js`. Exits **3** on timeout.

### `keyboard press` / `hotkey` / `type` / `down` / `up`
```json
{"pressed": "ENTER", "modifiers": ""}
{"hotkey": ["CONTROL", "S"]}
{"typed": "hello", "humanize": false}
```

### `mouse move` / `click` / `drag` / `hover`
```json
{"clicked": [100, 200], "button": "LEFT", "double": false, "humanize": false}
{"hover": "#menu", "at": [50, 12], "humanize": false}
```

### `scroll`
```json
{"scrolled": {"by_y": 500}}
{"scrolled": {"to_bottom": true, "loops": 3, "height": 12000}}
```

### `upload`
```json
{"selector": "input[type=file]", "files": ["/abs/a.png"], "via_chooser": false}
```

### `batch`
A list of per-URL records:
```json
[
  {"url": "https://a.com", "title": "A", "screenshot": "shots/0000.png", "query_result": "Hello", "error": null},
  {"url": "https://b.com", "title": null, "screenshot": null, "query_result": null, "error": "TimeoutError: ..."}
]
```

### `network watch`
Streams one JSON document per line (NDJSON), not a single document. Each line is:
```json
{"kind": "request", "request_id": "...", "url": "...", "method": "GET", "headers": {...}, "type": "XHR", "timestamp": 12345.6}
{"kind": "response", "request_id": "...", "url": "...", "status": 200, "mime_type": "application/json", "headers": {...}, "timestamp": 12345.7}
```

### `console logs`
A list of normalized console records, oldest first. Runtime (`console.*`,
uncaught errors) and Log (browser-generated messages) are merged and sorted by
`timestamp`. Works retroactively: Chrome buffers the current document's console
history (1000 entries, FIFO) and replays it when the command enables the
domains, so no prior arming is needed. History clears on navigation/reload.
```json
[
  {"source": "console-api", "level": "warning", "type": "warning",
   "text": "hydration mismatch",
   "url": "https://app.com/app.js", "line": 12, "column": 4,
   "timestamp": 1713370000123.4,
   "stack": [{"function": "render", "url": "https://app.com/app.js", "line": 12, "column": 4}]},
  {"source": "network", "level": "error", "type": "entry",
   "text": "Failed to load resource: the server responded with a status of 404",
   "url": "https://app.com/missing.png", "line": 0, "column": null,
   "timestamp": 1713370000200.0, "stack": null},
  {"source": "exception", "level": "error", "type": "exception",
   "text": "ReferenceError: undefinedFn is not defined",
   "url": "https://app.com/app.js", "line": 42, "column": 7,
   "timestamp": 1713370000300.0, "stack": [...]}
]
```
Every record has the same nine keys; absent fields are `null`.

| Field | Meaning |
| --- | --- |
| `source` | `console-api` (a `console.*` call), `exception` (uncaught JS error), or the Log-domain source: `network`, `security`, `deprecation`, `rendering`, … Matched by `--kind`. |
| `level` | `log` \| `debug` \| `info` \| `warning` \| `error`. Matched by `--level`. |
| `type` | CDP subtype: the raw console call type (`log`, `table`, `trace`, `assert`, …) for `console-api`; `exception`; `entry`. |
| `text` | Message text. Console args are stringified and space-joined; objects render via their CDP `description`/preview, never `null`. Matched by `--filter`. |
| `url` / `line` / `column` | Origin — the top stack frame for console calls, the throw site for exceptions. |
| `timestamp` | Milliseconds since epoch. Sort key. |
| `stack` | Call frames (`function`, `url`, `line`, `column`) or `null`. |

`console logs` returns as soon as the replay burst goes quiet (`--settle`,
default 0.3s, capped by `--timeout`); pass `--duration N` for a fixed window
when you also want to catch output emitted while it runs. `--clear` discards
the browser's history afterwards so the next read returns only what is new.

### `console watch`
Streams the same records as NDJSON (one JSON document per line), not a single
document. Enabling the domains replays the existing history first — pass
`--no-replay` to start from now. Runs until SIGINT or `--max-events`.

### `cloudflare auto-solve`
Long-running. Emits a final `{"auto_solve": "stopped", "duration": N or null}` on exit.

### `network block` / `mock` / `inject-header` / `fail`
Wrap pattern — these commands spawn the inner command as a subprocess and
emit whatever the inner command emits. The wrapping command itself prints
nothing on stdout (logs go to stderr). Exit code is the inner command's
exit code (or 2 if `--session`/`--connect` is missing, or 2 on bad args).

```bash
pydoll-cli --session s network block -t Image -t Stylesheet \
  -- get https://heavy-site.com
# stdout: {"url":"https://heavy-site.com","title":"..."}   <- from `get`
```

Fetch interception never sees a request that Chrome's HTTP cache serves, so on
a page the session already loaded, blocking looks like it did nothing. Confirm
on a fresh session or an unvisited URL. `getComputedStyle(document.body)
.backgroundColor` turning transparent and `document.images[0].naturalWidth ===
0` are reliable checks; `document.styleSheets.length` is not, because a blocked
`<link>` still contributes an (empty) entry.

### `extract`
With the schema's model. One record, or a list when `--all`.
```json
{"text": "A quote", "author": "Someone", "tags": ["t1","t2"], "year": null}
```

### `request`
```json
{
  "status": 200,
  "url": "https://…",
  "headers": {"content-type": "application/json"},
  "json": {"…": "…"},
  "text": null
}
```

### `session start`
```json
{
  "name": "agent-run",
  "pid": 31234,
  "port": 41721,
  "ws_url": "ws://127.0.0.1:41721/devtools/browser/XYZ",
  "user_data_dir": "/home/me/.cache/pydoll-cli/sessions/agent-run/user-data",
  "browser": "chrome",
  "binary": "/usr/bin/google-chrome",
  "started_at": 1713370000.42
}
```

### `session list`
A list of session objects, each extended with `"alive": true|false`. Leftover
profile dirs with no state file appear as `{"name", "orphan", "kept",
"size_bytes", "path"}` — reclaim the `"orphan": true` ones with
`session prune --orphans`. A `"kept": true` row was retained on purpose by
`stop --no-purge`, and `prune` skips it unless you pass `--include-kept`.

### `browsers`
```json
[{"kind": "chrome", "display_name": "Google Chrome", "path": "/usr/bin/google-chrome"}]
```

### `info`
```json
{
  "pydoll_cli": "0.5.0",
  "pydoll_python": "2.23.1",
  "browser": {
    "product": "Chrome/146.0.7680.153",
    "user_agent": "…",
    "revision": "…",
    "js_version": "…",
    "protocol_version": "1.3"
  }
}
```

## Attaching to an already-running browser

If the user already has Chrome/Wavebox/Edge running with `--remote-debugging-port=PORT`,
two patterns are available:

### One-shot attach with a fresh incognito tab

For a single command, use `--connect` + `--fresh` to get a new incognito browser
context + tab in the user's running browser, leaving their existing tabs alone.
The context is disposed when the command exits:

```bash
pydoll-cli --connect ws://127.0.0.1:9222/devtools/browser/XXX --fresh --output json \
  get https://example.com
```

`--new-tab` (default context) is the lighter-weight alternative when you want
to share cookies with the running browser but not hijack an existing tab.

### Persistent attached session (multi-step)

When you need *several* commands to share state (a search, follow-up clicks, an
extract, a screenshot), register an **attached session**. Two sub-modes:

**Incognito (default)** — zero cookies shared with the user; great for
unauthenticated research flows:

```bash
pydoll-cli session start research --attach --url https://www.google.com
pydoll-cli --session research query "h3" --all
pydoll-cli --session research click "h3"
pydoll-cli --session research source
pydoll-cli session stop research     # disposes the whole incognito context
```

**Shared profile** — pin a tab inside the user's real logged-in context. Use
this when you need access to authenticated pages (Gmail, LinkedIn, internal
dashboards) without bothering the user for creds. Three start modes:

| Flags                       | Behavior                                                                    |
| --------------------------- | --------------------------------------------------------------------------- |
| `--share-profile --url X`   | Adopt an existing tab containing X; otherwise create a new tab and navigate. Adopted tabs preserve scroll/state (no re-navigation). |
| `--share-profile --tab-url SUBSTR` | **Adopt-only.** Pin an existing tab matching SUBSTR. Errors with exit 4 if no match. Never creates a tab. |
| `--share-profile` (no URL)  | Create a fresh blank tab.                                                   |

```bash
# Adopt an existing tab (recommended when the page is already open)
pydoll-cli session start linkedin --attach --share-profile \
  --tab-url 'linkedin.com/feed'
pydoll-cli --session linkedin query 'a[href*="/in/"]' --all --attr href
pydoll-cli session stop linkedin     # leaves the user's tab open

# Or: open if missing, reuse if already there
pydoll-cli session start linkedin --attach --share-profile \
  --url https://www.linkedin.com/feed/
```

State files (`~/.cache/pydoll-cli/sessions/<NAME>.json`) include a
`created_target` boolean — `true` when we created the pinned tab, `false`
when we adopted an existing one. Visible in `session info` output.

`session stop` (shared-profile mode) **leaves the pinned tab open by
default** — pass `--close-tab` if you want to also close it. The browser
process is never killed.

In both modes, the tab (and incognito context, if any) are persisted; every
`--session <NAME>` call reuses that exact tab until you `session stop`. The
user's other tabs are never touched.

**Rule of thumb for agents:** default to `--share-profile` only when you
actually need the user's logins. For clean research / scraping, the default
incognito mode keeps the user's session hermetic. When you do need shared
profile and the page is already open, prefer `--tab-url SUBSTR` over `--url`
— it's the safest "ride along" pattern.

### Wavebox specifics

Wavebox's app-level account onboarding blocks a clean fresh launch (no CDP
readiness until the user logs in to Wavebox itself). So `session start --browser
wavebox` **defaults to `--attach`**: we probe port 9222 for a running Wavebox,
attach to it, and create the incognito context there. If no running Wavebox is
found, the command errors with a clear message explaining what to start.

Recommended Wavebox pattern when the user already has the target site open:

```bash
pydoll-cli --browser wavebox --output json session start work \
  --share-profile --tab-url 'github.com/anthropics'
```

Pass `--no-attach` if you want to insist on a fresh launch anyway (e.g. you
have a pre-seeded Wavebox profile past onboarding at `--user-data-dir`).

## Tips for agents

- **Prefer `query --all --attr href`** over scraping full HTML when you only
  need links — smaller payload, less context pressure.
- **Use `--session`** whenever you'll issue more than one command; each fresh
  launch costs ~1–2 seconds and a new Chrome profile.
- **Always `session stop`** when you're done — the browser process is
  detached and will survive the agent's own process. `stop` also deletes the
  session's profile from disk by default; pass `--no-purge` if you intend to
  `session start NAME` again and want to keep its login — that marks the
  profile `kept`, which `session prune` then leaves alone. Use `session prune
  --orphans` periodically to reclaim space from past sessions.
- **For element waiting**, pass `--wait N` to `query`/`click`/`type` rather
  than sleeping between commands.
- **Timeouts**: set `--timeout` on slow pages; the default of 30 seconds
  covers most sites.
- **Cloudflare**: if you hit a Turnstile challenge, use
  `pydoll-cli cloudflare bypass URL` and then continue with the same session.
