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
| 6    | Session not running        | `pydoll-cli session start …` first.                         |
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

### `eval`
```json
{"value": "Example Domain"}
```
`value` preserves the JS return type: string, number, bool, list, or object.

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
A list of session objects, each extended with `"alive": true|false`.

### `browsers`
```json
[{"kind": "chrome", "display_name": "Google Chrome", "path": "/usr/bin/google-chrome"}]
```

### `info`
```json
{
  "pydoll_cli": "0.1.0",
  "pydoll_python": "2.22.1",
  "browser": {
    "product": "Chrome/124.0.0.0",
    "user_agent": "…",
    "revision": "…",
    "js_version": "…",
    "protocol_version": "1.3"
  }
}
```

## Attaching to an already-running browser

If the user already has Chrome/Wavebox/Edge running with `--remote-debugging-port=PORT`,
pass `--connect ws://127.0.0.1:PORT/devtools/browser/...` to attach instead of
launching a new browser. Combine with `--fresh` so you operate in a new incognito
browser context + new tab, leaving the user's existing tabs and session untouched:

```bash
pydoll-cli --connect ws://127.0.0.1:9222/devtools/browser/XXX --fresh --output json \
  get https://example.com
```

`--new-tab` (default context) is the lighter-weight alternative when you want
to share cookies with the running browser but not hijack an existing tab.

## Tips for agents

- **Prefer `query --all --attr href`** over scraping full HTML when you only
  need links — smaller payload, less context pressure.
- **Use `--session`** whenever you'll issue more than one command; each fresh
  launch costs ~1–2 seconds and a new Chrome profile.
- **Always `session stop`** when you're done — the browser process is
  detached and will survive the agent's own process.
- **For element waiting**, pass `--wait N` to `query`/`click`/`type` rather
  than sleeping between commands.
- **Timeouts**: set `--timeout` on slow pages; the default of 30 seconds
  covers most sites.
- **Cloudflare**: if you hit a Turnstile challenge, use
  `pydoll-cli cloudflare bypass URL` and then continue with the same session.
