---
name: pydoll-cli
description: Drive a real Chromium browser via `pydoll-cli` for any task that touches a webpage — scrape, extract, click, fill a form, log in, screenshot, PDF, bypass Cloudflare, wait for dynamic content, read a page after JS runs. Use this whenever `pydoll-cli` is installed and the task involves navigating, interacting with, or extracting from a website. Prefer it over `curl`/`requests` (no JS) and over Playwright/Puppeteer scripts (heavier, slower to spin up). Triggers on phrases like "scrape <site>", "go to <url> and ...", "log into <site>", "automate <site>", "click the button", "fill the form", "take a screenshot of <url>", "save <page> as PDF", "extract data from <site>", "what does <site> say", "read/check <site>", "bypass Cloudflare", or any task that would otherwise need a headless browser. If `pydoll-cli` is not installed, tell the user `uv tool install pydoll-cli` (or `pipx install pydoll-cli` / `pip install pydoll-cli`) and carry on with this skill once it is.
---

# pydoll-cli

A CLI wrapper around [pydoll](https://github.com/autoscrape-labs/pydoll) that automates Chromium over the Chrome DevTools Protocol — no WebDriver, stealth defaults, stable JSON-on-stdout contract. Built so an AI agent can drive a real browser the same way it would drive `jq` or `gh`.

**Check it's installed:** `command -v pydoll-cli` — if absent, ask the user to `uv tool install pydoll-cli`.

## The one workflow to remember

For anything beyond a single `get`, use a persistent session. Launching Chrome costs 1–2 seconds per command otherwise.

```bash
# 1. Start a detached session (survives across invocations)
pydoll-cli --output json session start agent-run

# 2. Drive it — always pass --session NAME and --output json
pydoll-cli --output json --session agent-run get https://example.com
pydoll-cli --output json --session agent-run query "h1"

# 3. Stop it when done (the browser is detached; it will outlive your CLI run)
pydoll-cli --output json session stop agent-run
```

**`--output json` is a global flag — it must come BEFORE the subcommand**, not after. `pydoll-cli session start agent-run --output json` fails with "No such option: --output". Same goes for `--session`. Get the order right once and the rest is muscle memory.

**`--output json` is a stable contract.** Every command emits one JSON document on stdout. Stderr has logs/progress — ignore it.

**Headless is the default.** If the user wants to *watch* the browser drive itself, pass the global `--no-headless` flag (before the subcommand): `pydoll-cli --no-headless --output json session start agent-run`. There is no per-session toggle — set it at session-start time. (`session start --help` shows `--no-headless` in its example without listing it as a session-level option, which is misleading: it's a *global* flag.)

## Command quick-reference

Pass `--session NAME --output json` on every call below (omitted here for brevity). Exit code is the primary failure signal; see table at the bottom.

| Command | What it does | Stdout shape |
| --- | --- | --- |
| `get URL` | Navigate (reuses the session's current tab) | `{"url","title"}` |
| `source` | Full HTML of current page | `{"html","bytes"}` |
| `text [--selector S]` | Visible text of page or element | `{"text"}` |
| `query S [--all] [--attr A] [--wait N]` | Find element(s); `--attr href` for links | `{"text","attr","tag"}` or list |
| `click S [--wait N] [--fast]` | Click (humanized cursor curve by default; `--fast` for raw JS click) | `{"clicked","url"}` |
| `type S "text" [--human] [--delay-ms N]` | Type into an input. `--human` = pydoll variable-cadence + ~2% typos; `--delay-ms N` = constant N-ms cadence; default = instant `insert_text` | `{"selector","typed"}` |
| `eval --script "..."` | Run JS, return value (by-value by default) | `{"value": <typed>}` |
| `screenshot [URL] -o FILE [--full-page] [--selector S]` | PNG/JPEG | `{"path": ...}` |
| `pdf [URL] -o FILE [--landscape]` | PDF | `{"path": ...}` |
| `extract URL --schema file.py --schema-class C --scope S --all` | Pydantic-schema extraction | record or list |
| `cloudflare bypass URL -o page.html` | Solve Turnstile then dump HTML | `{"url","bytes","path"}` |
| `request METHOD URL [--json '{...}'] [-H "K: V"]` | HTTP carrying browser cookies | `{"status","url","headers","json","text"}` |
| `tabs list \| new --url URL \| close --target-id ID \| focus INDEX` | Multi-tab control | see below |
| `cookies get \| set --file cookies.json \| clear` | Cookie jar | array / ack |
| `session start \| stop \| list \| info NAME` | Session lifecycle | see start shape above |

For any flag you're unsure about: `pydoll-cli <command> --help`. It always has a concrete example.

## Critical gotchas (learned the hard way)

### 1. `get URL` with `--session` reuses the **current tab**. It does NOT open a new one.

To actually open a new tab, use `tabs new`:
```bash
pydoll-cli --session s --output json tabs new --url https://example.com
```

### 2. `tabs list` order is unstable — new tabs appear at **index 0**.

Indices shift every time you open a tab. For any cross-invocation reference, capture `target_id` and use `--target-id`:
```bash
TID=$(pydoll-cli --session s --output json tabs new --url https://x.com | jq -r .target_id)
# ...later...
pydoll-cli --session s --output json tabs close --target-id "$TID"
```

### 3. Naive selectors over-collect on list pages.

`span.title a` often matches nested anchors too (tag links, "from:site" chips, etc.). Prefer **direct child** for list scraping:
```css
span.title > a    /* only the direct child, not nested <a>s */
```
If `query --all` returns suspiciously many items or "text" / "attr" repeats in odd ways, that's the tell.

### 4. When a selector "isn't found" on a JS-heavy page, don't just crank `--wait`.

The selector may be wrong. Inspect reality:
```bash
pydoll-cli --session s --output json source | jq -r .html | head -100
# or, faster:
pydoll-cli --session s --output json eval --script \
  'Array.from(document.querySelectorAll("a")).slice(0,20).map(a=>({t:a.innerText.slice(0,40), h:a.href}))'
```

For search engines (Google, DuckDuckGo, Bing), a **direct URL with `?q=`** is almost always less brittle than typing into the search box and waiting for SPA results.

### 5. `extract --schema` — `attribute=`, NOT `extract=`, and the import is `pydoll.extractor`

```python
# schema.py
from pydoll.extractor import ExtractionModel, Field   # pydoll, not pydoll_cli

class Item(ExtractionModel):
    title: str = Field(selector=".row > a")                      # default = innerText
    url:   str = Field(selector=".row > a", attribute="href")    # any HTML attribute
    # Optional: transform for type coercion, e.g. int:
    # points: int = Field(selector=".score", transform=lambda s: int(s.split()[0]))
```
```bash
pydoll-cli --output json extract URL \
  --schema schema.py --schema-class Item --scope ".row" --all
```
`--scope` is the repeating-element selector; fields inside resolve **relative to it**. `--all` returns a JSON array. Omit `--all` for a single record scoped to the whole page.

> Schemas are loaded by pydoll-cli's **bundled Python**. A bare `python3 -c "from pydoll..."` in your shell will fail with `ModuleNotFoundError` — that's expected and not a problem with the schema.

### 6. `cloudflare bypass` with `--output json` does NOT emit HTML

JSON mode returns only `{url, bytes, path?}`. To actually capture the page, pass `-o`:
```bash
pydoll-cli --output json cloudflare bypass URL -o page.html
# Then parse page.html for whatever you need.
```

If `bypass` returns but the page is **still showing the challenge**, the Turnstile widget hadn't rendered yet within the default 5s detection window. Bump it:
```bash
pydoll-cli --output json cloudflare bypass URL --captcha-timeout 15 -o page.html
```

### 7. `screenshot` / `pdf` need an output target

No default destination. Always `-o shot.png` (or `--base64` to stream to stdout). For "whole page beyond viewport" add `--full-page`.

### 8. `eval --script` returns values, not references

By default JS return values are serialized: `{a:1}` → `{"value":{"a":1}}`, arrays → arrays, etc. Only pass `--as-ref` if you specifically need a handle to a DOM node to reuse in a later eval. You almost never do.

### 9. On errors you'll see a Python traceback — exit codes are still the truth

pydoll-cli prints Rich tracebacks on unhandled exceptions, which can look alarming, but `echo $?` still tells you what happened:

| Code | Meaning | Do |
| --- | --- | --- |
| 0 | Success | proceed |
| 1 | Generic failure | read stderr, retry or fail |
| 2 | CLI arg error (bad flag, bad schema load, etc.) | fix the args |
| 3 | Timeout | retry with `--timeout N` |
| 4 | Element not found | fix the selector, or add/raise `--wait N` |
| 5 | Browser launch failed | check the binary, maybe `--in-container` in Docker |
| 6 | Session not running | `pydoll-cli session start NAME` first |
| 7 | JavaScript exception in `eval` | fix the JS or check the page state; `value.description` is in stderr |
| 130 | Ctrl-C | user aborted |

### 10. **Never** add `--no-sandbox` or `--ignore-certificate-errors` by hand

Use `--in-container` in Docker/CI (it adds `--no-sandbox` + `--disable-dev-shm-usage` together, safely). On a normal desktop, leave the sandbox on.

For authenticated proxies (Bright Data, etc.) that present an internal CA cert, use `--proxy-insecure` instead of `-a --ignore-certificate-errors`:
```bash
pydoll-cli --proxy http://user:pass@proxy:8080 --proxy-insecure get https://target.com
```

### 11. `eval --script` exits 7 on JS error — and quoting still bites

Since 0.1.6, a JS exception (syntax error, undefined ref, anything) makes `eval` exit code **7** and writes `error: JS error: <description>` to stderr. So `set -e` / `||` wiring works the way you'd expect — no manual `jq -e '.value.subtype == "error"'` check needed.

The other foot-gun is still quoting. Bash double-quoted strings + escaped `\"` inside JS hurts. **Single-quote your script** so JS can use raw `"`. For multi-line/complex scripts, write to a file and inline with `$(cat script.js)`:
```bash
pydoll-cli --output json --session s eval --script "$(cat /tmp/extract.js)"
```

`eval` also awaits any Promise the script returns (via CDP `awaitPromise`), so async one-liners just work:
```bash
pydoll-cli --output json --session s eval --script \
  '(async () => (await fetch("/api/me")).status)()'
```

### 12. `get URL` does NOT wait for SPA hydration

It waits for the navigation event, not for React/Vue/etc. to render. On modern SPAs (LinkedIn, Twitter, most dashboards), `get` returns while `document.body.innerText` is still ~50 lines of skeleton/nav. Patterns:

- **Cheap and works:** `sleep 3 && eval "..."`. Crude but reliable for known-fast pages.
- **Heavy aggregators want 20–30s, not 3.** Flight/hotel/listing aggregators (Kayak, Expedia, Booking, Skyscanner) progressively populate results from multiple back-ends. A `sleep 13` returned `0 of N flights` on Kayak result pages where `sleep 25` returned the actual cheapest fare. If you're getting empty/partial results from one of these sites, **don't conclude "no flights" — extend the wait**, or better, poll.
- **Better:** poll for the content selector to exist, then extract. Single-quote the bash string so JS keeps its raw `"` (per gotcha #11):
  ```bash
  pydoll-cli --output json --session s eval --script '
    new Promise(res => {
      const start = Date.now();
      const tick = () => document.querySelectorAll("a[href*=\"/in/\"]").length > 5
        ? res({ready:true, ms:Date.now()-start})
        : Date.now()-start > 8000 ? res({ready:false}) : setTimeout(tick, 200);
      tick();
    })
  '
  ```
  pydoll-cli **does** await Promises returned from `eval --script`.
- **Best for aggregators: poll on a *stability* signal, not just presence.** Aggregators show partial results within seconds and keep adding. Wait until either (a) a progress indicator disappears, or (b) the result count stops growing for ~2s:
  ```bash
  pydoll-cli --output json --session s eval --script '
    new Promise(res => {
      let last = -1, stable = 0, start = Date.now();
      const tick = () => {
        const n = document.querySelectorAll("[class*=resultWrapper], [data-resultid]").length;
        if (n > 0 && n === last) stable++; else { stable = 0; last = n; }
        if (stable >= 4) return res({ready: true, count: n, ms: Date.now()-start});  // ~2s stable
        if (Date.now() - start > 35000) return res({ready: false, count: n});
        setTimeout(tick, 500);
      };
      tick();
    })
  '
  ```
- For static-pagination SPAs, **don't bother scrolling unless you've confirmed lazy-load**. A reflexive `window.scrollTo(0, document.body.scrollHeight)` cost me ~30s across a 25-page run on a page where all 10 cards were already rendered.

### 13. For paginated SPAs, prefer URL params over clicking "Next"

Most search/list SPAs accept `?page=N` (or `?cursor=`, `?offset=`) directly. Going through the URL:

- Skips brittle "Next button" selectors that change with redesigns
- Lets you parallelize / resume / cap easily
- The page reuses the SPA's own router, so JS still hydrates as normal

Only fall back to clicking pagination controls when the URL truly doesn't carry pagination state (rare). Stop conditions: empty result list, OR the first item URL on page N matches page N-1 (some sites clamp instead of erroring past the last page — LinkedIn does this).

### 14. For logged-in scraping, consider `pydoll-cli request` over DOM scraping

`request` reuses the browser's cookies, so any internal JSON API the site already calls is reachable directly:
```bash
pydoll-cli --output json --session s request GET 'https://site.com/api/endpoint?...' \
  -H 'x-api-version: 2' -H 'accept: application/json'
```
Returns `{status, json, ...}` — no DOM parsing, no hydration waits, ~10× faster for paginated lists. Catch is finding the endpoint: open DevTools Network tab in the user's browser, filter to XHR, copy the request. For LinkedIn/Twitter/etc., the endpoints exist but may need additional headers (`csrf-token`, `x-li-track`) — get these from a real browser request first.

DOM scraping is still right when: (a) the site renders entirely server-side, (b) you can't get the auth headers right, or (c) it's a one-shot.

## Attached sessions: driving the user's logged-in Chrome

If the user already has Chrome (or Wavebox/Edge) running with `--remote-debugging-port=9222` and wants an action performed against a **logged-in site** (Gmail, LinkedIn, internal dashboards), attach instead of launching fresh:

```bash
# Incognito attach (default) — zero cookie sharing, great for research
pydoll-cli --output json session start research --attach --url https://…

# Shared-profile attach — pin a tab in the user's real logged-in profile
pydoll-cli --output json session start work --attach --share-profile --url https://…
pydoll-cli --output json --session work query '…'
pydoll-cli --output json session stop work   # closes only the pinned tab; user's browser lives on
```

**Rule of thumb:** default to **incognito** (no `--share-profile`). Opt into `--share-profile` only when you actually need the user's login state. Actions in shared-profile mode appear in the user's real history, so scope them tightly.

**What you'll see on screen:**
- **Incognito attach (default)** opens a **new incognito/private window** in the user's browser — Chromium can't put an incognito context inside a non-incognito window. The session response shows a non-null `browser_context_id`. `session stop` closes that window cleanly.
- **`--share-profile`** opens a **new tab in an existing window**, sharing cookies with the user's logged-in session. `browser_context_id` is `null`. `session stop` closes only that tab.

If the user is surprised by a window popping up, check whether you actually need login state — if not, incognito is correct (and the new window is expected); if you do, add `--share-profile`.

**Wavebox users:** Wavebox runs Chromium with CDP on `:9222` if you launched it with `--remote-debugging-port=9222`; verify with `curl -s http://127.0.0.1:9222/json/version`. Then use the global `--browser wavebox` flag (it auto-enables `--attach` since Wavebox blocks fresh CDP launches) — note `--browser` goes **before** the subcommand, like `--output`:
```bash
pydoll-cli --browser wavebox --output json session start work --share-profile --url 'https://...'
```
Don't try to `--no-attach` against Wavebox — its app-level onboarding blocks fresh launches.

**Confirm you're authenticated** before doing real work (a dev-tools-disabled login wall returns ~3KB of skeleton HTML that looks like nothing went wrong):
```bash
pydoll-cli --output json --session s eval --script \
  'JSON.stringify({url:location.href, title:document.title, isLogin: !!document.querySelector("input[name=session_key],form[action*=login]")})'
```

## Anti-patterns

- **Don't** use `curl` / `requests` on a page that needs JS. Use `get` + `source` or `eval`.
- **Don't** write a fresh Playwright/Puppeteer/Selenium script when `pydoll-cli` is available — the whole point is to save that work.
- **Don't** launch a new browser for every step of a multi-step task. Start one session, reuse it, stop it at the end.
- **Don't** forget `session stop` — the browser is **detached** and will outlive your CLI run.
- **Don't** parse stderr or treat a zero-byte stdout as success. `--output json` + exit code are the contract.
- **Don't** guess selectors forever. If `query`/`click` returns "not found", inspect `source` or `eval` the DOM — the page is usually just different than you assumed.
- **Don't** scroll just-in-case. If the page renders all items in the initial DOM (most search/list pages with explicit pagination), scrolling adds latency for nothing. Verify lazy-load is real first (check `document.body.scrollHeight` before/after a scroll, or `document.querySelectorAll(".item").length`).
- **Don't** wire JS-error checks around `.value.subtype == "error"` anymore — `eval` exits 7 on a JS exception (since 0.1.6) and the description is on stderr.
- **Don't** conclude "no results" from a single short wait on an aggregator (Kayak/Expedia/Booking/Skyscanner). These sites return `0 of N` for tens of seconds before populating. Poll for stability (gotcha #12) before declaring a route empty.

## When this skill is installed from the pydoll-cli repo

See `AGENTS.md` in the repo for the full JSON-shape catalog per subcommand, attached-session patterns (`--connect`, `--fresh`, `--new-tab`), Wavebox specifics, and niche commands (`har record/replay`, `network logs`, `run SCRIPT.py`, `shell`). This skill covers the ~90% path; `AGENTS.md` is the reference for the rest.

Repository: https://github.com/dovidgefen/pydoll-cli
