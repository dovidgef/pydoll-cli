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
pydoll-cli --output json --session agent-run wait --selector ".content"
pydoll-cli --output json --session agent-run query "h1"

# 3. Stop it when done (the browser is detached; it will outlive your CLI run)
pydoll-cli --output json session stop agent-run
```

**`--output json` is a global flag — it must come BEFORE the subcommand**, not after. `pydoll-cli session start agent-run --output json` fails with "No such option: --output". Same goes for `--session`. Get the order right once and the rest is muscle memory.

**For SPA-heavy work, start the session with `--page-load-state interactive`.** Returns from `get` as soon as DOMContentLoaded fires (~2–5× faster than waiting for full `load`). You then chain a `wait --selector` or `wait --stable-ids` to gate on the actual content you need. This pattern is the 0.2.0-shaped default for sites like LinkedIn, Twitter, Kayak, Expedia.

**`--output json` is a stable contract.** Every command emits one JSON document on stdout. Stderr has logs/progress — ignore it.

**Headless is the default.** If the user wants to *watch* the browser drive itself, pass the global `--no-headless` flag (before the subcommand): `pydoll-cli --no-headless --output json session start agent-run`. There is no per-session toggle — set it at session-start time. (`session start --help` shows `--no-headless` in its example without listing it as a session-level option, which is misleading: it's a *global* flag.)

**Headless + bot-protected sites: spoof the UA at session-start.** Headless Chrome's default User-Agent contains the literal token `HeadlessChrome/...`, which heavily-protected destinations (search engines, ticketing/airlines, social platforms, Cloudflare-fronted sites) match in a one-line check. Symptom: a "challenge" / "unusual traffic" / `/sorry/` page where a logged-out browser would have served real HTML. Set the `--user-agent` global to a current desktop Chrome string (matches the major version pydoll launches — see `pydoll-cli info | grep product`):
```bash
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36'
pydoll-cli --user-agent "$UA" --webrtc-leak-protection --output json session start agent
```
Verify it took: `pydoll-cli --session agent eval --script 'navigator.userAgent'` should print no `Headless`. Headed (`--no-headless`) drops the `Headless` token automatically — this gotcha is headless-only.

## Command quick-reference

Pass `--session NAME --output json` on every call below (omitted here for brevity). Exit code is the primary failure signal; see table at the bottom.

| Command | What it does | Stdout shape |
| --- | --- | --- |
| `get URL` | Navigate (reuses the session's current tab) | `{"url","title"}` |
| `source` | Full HTML of current page | `{"html","bytes"}` |
| `text [--selector S] [--all]` | Visible text of page or element. `--all` returns every match | `{"text"}` or `{"texts":[...],"count":N}` |
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
| `session start \| stop \| list \| info \| rm NAME \| prune --orphans` | Session lifecycle + disk cleanup (`stop` deletes the profile by default; `--no-purge` keeps it) | see start shape above |
| `wait --selector S \| --network-idle \| --url-contains S \| --page-event E \| --js EXPR \| --stable-ids "S\|ATTR"` | Block until a page condition is satisfied (overall `--wait N` timeout) | `{"ready":true,"ms":N,"matched":...}` |
| `get URL --wait-for SELECTOR --wait N` | Navigate AND wait for a selector (one round-trip) | `{"url","title","wait_for"}` |
| `keyboard press KEY [--modifiers M[,M]] \| hotkey K1 K2 [K3] \| type "text" [--humanize] \| down KEY \| up KEY` | Page-level key input | `{"pressed"\|"hotkey"\|"typed":...}` |
| `mouse move X Y \| click X Y [--button B] [--double] \| drag X1 Y1 X2 Y2 \| hover SELECTOR` | Coordinate-based mouse input | `{"clicked":[X,Y],"button":...}` etc. |
| `scroll --by-y N \| --to-y N \| --to-bottom [--max-loops N] [--idle-ms M] \| --to-selector S` | Page scrolling, including infinite-scroll loops | `{"scrolled":{...}}` |
| `upload SELECTOR FILE [FILE...] [--via-chooser]` | Set files on `<input type=file>` (default) or via the file-chooser dialog (`--via-chooser`) | `{"selector","files","via_chooser"}` |
| `batch URL [URL...] [--screenshot-dir D] [--source-dir D] [--query S] [--concurrency N]` | Visit many URLs in parallel tabs (one tab per URL, asyncio.gather) | `[{"url","title","screenshot","query_result","error"},...]` |
| `network watch [--max-events N] [--kind {request,response,both}] [--filter STR]` | Stream NDJSON events to stdout until SIGINT or `--max-events` | one JSON per line |
| `cloudflare auto-solve [--duration N] [--captcha-timeout N]` | Background Turnstile solver — pair with `--session` and let other CLI calls drive the same browser | `{"auto_solve":"stopped"}` on exit |
| `network block -t T... -- CMD ARGS` | Block resources by type during the inner command (Image/Stylesheet/Font/...) | inner command's stdout |
| `network mock -p URL_SUBSTR --status N --body FILE [-H K:V] -- CMD ARGS` | Stub matching requests | inner command's stdout |
| `network inject-header -p URL_SUBSTR -H K:V... -- CMD ARGS` | Add headers to matching requests | inner command's stdout |
| `network fail -p URL_SUBSTR [--reason R] -- CMD ARGS` | Fail matching requests with a CDP ErrorReason | inner command's stdout |

For any flag you're unsure about: `pydoll-cli <command> --help`. It always has a concrete example.

## Critical gotchas (learned the hard way)

### 1. `get URL` with `--session` reuses the **current tab**. It does NOT open a new one.

To actually open a new tab, use `tabs new`:
```bash
pydoll-cli --session s --output json tabs new --url https://example.com
```

**`tabs new` does not shift focus.** Subsequent `--session NAME` calls without `--tab N` / `--tab-url SUBSTR` keep targeting the previous tab. Pin the new tab on each call (`--tab-url` is stable across the session; index isn't — see #2):
```bash
pydoll-cli --session s --output json tabs new --url https://x.com
pydoll-cli --session s --tab-url 'x.com' --output json query 'h1'
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

If `screenshot --full-page` hangs the first time on a fresh tab (seen on Chrome 146 with `--page-load-state interactive`), the renderer hasn't laid out content past the viewport yet. Either wait for full load before the capture, or take a viewport screenshot first to warm the renderer:
```bash
pydoll-cli --session s --output json wait --js 'document.readyState === "complete"'
pydoll-cli --session s --output json screenshot -o shot.png --full-page
```

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

### 12. SPA hydration: pick the right wait primitive

`get URL` returns when navigation fires, not when React/Vue/etc. has rendered. On modern SPAs (LinkedIn, Twitter, most dashboards), `get` returns while `document.body.innerText` is still ~50 lines of skeleton/nav. Decision tree:

- **Static or fast page:** just `get URL` (default).
- **SPA where you only need the DOM tree:** start the session with `--page-load-state interactive` (~2–5× faster on JS-heavy pages).
- **Wait for content right after navigation:** `get URL --wait-for ".content" --wait 30` (one round-trip).
- **Wait between commands:** `wait --selector ".content" --wait 30` — uses `tab.query` polling; supports `--count N` for "at least N matches".
- **Wait for SPA route change after a click:** `wait --url-contains /dashboard --wait 10`.
- **Wait for a CDP page event:** `wait --page-event {load,dom-content,frame-navigated}`. `load` and `dom-content` auto-resolve when the page is already past that milestone (checks `document.readyState` first); `frame-navigated` always listens for the *next* navigation, so use it only when one is pending — for "did this `click` cause a nav?", prefer `wait --url-contains '/expected'`.
- **Aggregator with progressive results (Kayak/Expedia/Booking/Skyscanner):** `wait --stable-ids ".result|data-id" --stable-ms 2000 --wait 35`. Counts unique IDs and resolves when no new ones appear for `--stable-ms`. Far better than polling on raw count — count goes flat between batches even while data is still loading.
- **Network settled** (use only when no selector/URL signal exists — Playwright's docs explicitly discourage networkidle): `wait --network-idle --idle-ms 500`.
- **Wait for arbitrary JS to become truthy:** `wait --js 'document.readyState === "complete" && window.app.ready'` (server-side Promise loop, single CDP call).
- **Last resort, only if none of the above fits:** `eval --script` with your own Promise. `eval` awaits Promises and exits 7 on JS error (gotcha #11).

For static-pagination SPAs, **don't scroll just-in-case**. If `document.body.scrollHeight` doesn't grow after a `scroll --by-y 1000`, the page wasn't lazy-loading — you wasted seconds.

### 13. For paginated SPAs, prefer URL params over clicking "Next"

Most search/list SPAs accept `?page=N` (or `?cursor=`, `?offset=`) directly. Going through the URL:

- Skips brittle "Next button" selectors that change with redesigns
- Lets you parallelize / resume / cap easily
- The page reuses the SPA's own router, so JS still hydrates as normal

Only fall back to clicking pagination controls when the URL truly doesn't carry pagination state (rare). Stop conditions: empty result list, OR the first item URL on page N matches page N-1 (some sites clamp instead of erroring past the last page — LinkedIn does this).

### 14. For list/feed scraping: `pydoll-cli request` is the right default

`request` reuses the browser's cookies, so any internal JSON API the site already calls is reachable directly:
```bash
pydoll-cli --output json --session s request GET 'https://site.com/api/endpoint?...' \
  -H 'x-api-version: 2' -H 'accept: application/json'
```
Returns `{status, json, ...}` — no DOM parsing, no hydration waits, ~10× faster for paginated lists. Catch is finding the endpoint: open DevTools Network tab in the user's browser, filter to XHR, copy the request. For LinkedIn/Twitter/etc., the endpoints exist but may need additional headers (`csrf-token`, `x-li-track`) — get these from a real browser request first.

`request` issues `fetch()` from the **current tab's page context**, so the page's CSP applies — strict `connect-src` (HN, GitHub, etc.) blocks cross-origin fetches with `TypeError: Failed to fetch` even when the target host accepts CORS. Workaround: navigate to a permissive page first.
```bash
pydoll-cli --session s --output json get https://example.com    # any page without strict CSP
pydoll-cli --session s --output json request GET https://api.target.com/x   # works
```
Cookies are sent based on the **target** host's jar, so the detour doesn't cost you auth. `about:blank` doesn't work — pydoll reads `document.cookie` after the fetch and that throws on `about:blank`.

**For virtualized lists** (React virtual-scroll, infinite scroll), DOM scraping is unreliable because rows recycle as you scroll — `query --all` returns a sliding window, not the full list. Use `request` against the underlying API. If you must use the DOM, gate on `wait --stable-ids` (not stable-count — count stays flat *between* batches while new data is still loading).

DOM scraping is still right when: (a) the site renders entirely server-side, (b) you can't reverse the auth headers, or (c) it's a one-shot of a single page.

### 15. Iframes: just write the selector through them

pydoll auto-splits selectors at `iframe`. No need to switch frames manually:
```bash
pydoll-cli --session s query "iframe[src*=checkout] > #pay-button"
pydoll-cli --session s query "iframe.outer > iframe.inner > .content"
```
Works for both CSS combinators and XPath. See pydoll iframe docs for the full split rules.

### 16. `wait`/`query --wait N` is presence, not interactivity

Unlike Playwright, pydoll's `query` / `click` / `type --wait N` polls for the element to *exist in the DOM*. It does NOT verify visibility, enablement, animation stability, or that the element actually receives events.

Symptom: `click` runs (exit 0) but the page doesn't react. Cause: element exists but is hidden behind a modal, disabled, or still animating in.

Fix: chain a JS check before the click:
```bash
pydoll-cli --session s wait --js '!!document.querySelector(".btn:not([disabled])")'
pydoll-cli --session s click ".btn"
```

### 17. Mouse / keyboard / scroll have their own command groups

For coordinate-based clicks (canvas, drag-and-drop, hover-only menus) use `mouse click X Y` / `mouse drag` / `mouse hover SELECTOR` — *don't* `eval` `tab.mouse`. For global hotkeys (Ctrl+S, F12) use `keyboard hotkey CONTROL S` / `keyboard press F5` / `keyboard type "text" [--humanize]`. For infinite scroll use `scroll --to-bottom --max-loops 10 --idle-ms 800` (loops until `scrollHeight` stops growing) — *don't* hand-roll `window.scrollTo` in `eval`. `--help` on each for full flags.

### 18. Parallel scraping: `batch` instead of N sequential `get`s

Scraping 10 URLs sequentially via `--session` + `get` costs ~10× the per-page time. `batch` opens one tab per URL, drives them in parallel via `asyncio.gather`, and returns one record per URL with title / screenshot / query_result / error:
```bash
pydoll-cli --output json batch https://a.com https://b.com https://c.com \
  --query "h1" --concurrency 3 --screenshot-dir shots/
```
~10× speedup vs sequential for unrelated URLs. Use a single `--session` with `wait` between calls when the URLs need to share cookies / state.

### 19. File uploads: `upload`, not `eval`

For a visible file input: `pydoll-cli --session s upload 'input[type=file]' /path/to/a.png /path/to/b.png`. For hidden inputs behind a styled button (the common React/Tailwind pattern), pass `--via-chooser` and SELECTOR becomes the *button*: `pydoll-cli --session s upload '.upload-btn' /path/to/a.png --via-chooser`. The CLI clicks the button inside an `expect_file_chooser()` context that sets the files when the dialog opens.

### 20. Network interception: wrap pattern

Four interceptor commands wrap an inner command and apply CDP Fetch interception only for its duration. **All require `--session NAME`** — the inner command runs as a subprocess against the same browser:

```bash
# Block heavy resources for one request — common ~2× speedup on image-heavy pages.
pydoll-cli --session s network block -t Image -t Stylesheet -t Font \
  -- screenshot https://heavy-site.com -o shot.png

# Mock an API endpoint (response body is the file's bytes, base64-encoded for you).
pydoll-cli --session s network mock -p /api/me --status 200 --body fixture.json \
  -- get https://app.com

# Inject auth headers into matching requests.
pydoll-cli --session s network inject-header -p /api/ \
  -H "Authorization: Bearer xyz" \
  -- request GET https://app.com/api/me

# Simulate failures (default reason TIMED_OUT).
pydoll-cli --session s network fail -p /track/ --reason CONNECTION_REFUSED \
  -- get https://app.com
```

`-p PATTERN` is a substring match against the request URL. `-t TYPE` is one of `Document/Stylesheet/Image/Media/Font/Script/XHR/Fetch/WebSocket/...` (case-insensitive). On URL/type miss, the request continues unmodified — the wrapper only intercepts what matches.

`network mock` is the testing-side complement to `request` (gotcha #14): when you want to drive the page but stub the API.

**Cross-origin mocks need `Access-Control-Allow-Origin`.** The browser still CORS-checks fulfilled responses, so a mock for a host different from the page's origin must include the header or the inner `fetch()` (or `request`) fails with `TypeError: Failed to fetch`:
```bash
pydoll-cli --session s network mock -p /api/me --status 200 --body fixture.json \
  -H 'content-type: application/json' \
  -H 'access-control-allow-origin: *' \
  -- request GET https://api.other-host.com/api/me
```
Same-origin mocks (page is on `app.com`, mocking `app.com/api/...`) don't need it.

The `--` separator is conventional but not required — the wrapping command captures everything after the recognized options as the inner command.

## Attached sessions: driving the user's logged-in Chrome

If the user already has Chrome (or Wavebox/Edge) running with `--remote-debugging-port=9222` and wants an action performed against a **logged-in site** (Gmail, LinkedIn, internal dashboards), attach instead of launching fresh:

```bash
# Incognito attach (default) — zero cookie sharing, great for research
pydoll-cli --output json session start research --attach --url https://…

# Shared-profile attach — pin a tab in the user's real logged-in profile.
# If `--url` is already open in another tab, that tab is adopted as-is
# (no duplicate tab, no re-navigation). Otherwise a new tab is created.
pydoll-cli --output json session start work --attach --share-profile --url https://…
pydoll-cli --output json --session work query '…'
pydoll-cli --output json session stop work   # leaves the pinned tab open by default
```

**Rule of thumb:** default to **incognito** (no `--share-profile`). Opt into `--share-profile` only when you actually need the user's login state. Actions in shared-profile mode appear in the user's real history, so scope them tightly.

**Adopt an existing tab (don't spawn a new one).** When the user already has the target site open and wants the agent to ride along on *that* tab — especially common with Wavebox — use `--tab-url SUBSTR` instead of `--url`:
```bash
pydoll-cli --browser wavebox --output json session start work \
  --share-profile --tab-url 'github.com/anthropics'
```
`--tab-url` is **adopt-only**: it errors with exit 4 if no open tab matches. Adopted tabs are flagged `created_target=false` in `session info`, and `session stop` leaves them open by default. Add `--close-tab` to `session stop` if you do want to close the tab as part of teardown.

**What you'll see on screen:**
- **Incognito attach (default)** opens a **new incognito/private window** in the user's browser — Chromium can't put an incognito context inside a non-incognito window. The session response shows a non-null `browser_context_id`. `session stop` closes that window cleanly.
- **`--share-profile` with `--url` (matching tab exists)** adopts the existing tab; nothing visible changes. `browser_context_id` is `null`, `created_target` is `false`.
- **`--share-profile` with `--url` (no match) or no URL** opens a new tab in an existing window, sharing cookies with the user's logged-in session. `created_target` is `true`.
- **`--share-profile` with `--tab-url`** adopts a matching tab without ever creating one. Errors if no match.
- **`session stop` (shared-profile)** removes state but leaves the pinned tab open by default. Pass `--close-tab` to also close it (pre-0.3.2 behavior).

If the user is surprised by a window popping up, check whether you actually need login state — if not, incognito is correct (and the new window is expected); if you do, add `--share-profile` and prefer `--tab-url` when the page is already open.

**Wavebox users:** Wavebox runs Chromium with CDP on `:9222` if you launched it with `--remote-debugging-port=9222`; verify with `curl -s http://127.0.0.1:9222/json/version`. Then use the global `--browser wavebox` flag (it auto-enables `--attach` since Wavebox blocks fresh CDP launches) — note `--browser` goes **before** the subcommand, like `--output`:
```bash
# Recommended: ride along on the tab the user already has open.
pydoll-cli --browser wavebox --output json session start work \
  --share-profile --tab-url 'partial-url-of-open-tab'

# Or: open/reuse a specific URL.
pydoll-cli --browser wavebox --output json session start work \
  --share-profile --url 'https://...'
```
Don't try to `--no-attach` against Wavebox — its app-level onboarding blocks fresh launches.

**Proxied research?** Add `--webrtc-leak-protection` (enables pydoll's WebRTC suppression). Otherwise WebRTC reveals the real IP independently of the HTTP proxy — a known fingerprinting hole.

**Confirm you're authenticated** before doing real work (a dev-tools-disabled login wall returns ~3KB of skeleton HTML that looks like nothing went wrong):
```bash
pydoll-cli --output json --session s eval --script \
  'JSON.stringify({url:location.href, title:document.title, isLogin: !!document.querySelector("input[name=session_key],form[action*=login]")})'
```

## Anti-patterns

- **Don't** use `curl` / `requests` on a page that needs JS. Use `get` + `source` or `eval`.
- **Don't** write a fresh Playwright/Puppeteer/Selenium script when `pydoll-cli` is available — the whole point is to save that work.
- **Don't** launch a new browser for every step of a multi-step task. Start one session, reuse it, stop it at the end.
- **Don't** forget `session stop` — the browser is **detached** and will outlive your CLI run. `stop` now also deletes the session's profile dir (use `--no-purge` to keep a login for restart); run `session prune --orphans` to reclaim disk from old sessions.
- **Don't** parse stderr or treat a zero-byte stdout as success. `--output json` + exit code are the contract.
- **Don't** guess selectors forever. If `query`/`click` returns "not found", inspect `source` or `eval` the DOM — the page is usually just different than you assumed.
- **Don't** scroll just-in-case. If the page renders all items in the initial DOM (most search/list pages with explicit pagination), scrolling adds latency for nothing. Verify lazy-load is real first (check `document.body.scrollHeight` before/after a scroll, or `document.querySelectorAll(".item").length`).
- **Don't** wire JS-error checks around `.value.subtype == "error"` anymore — `eval` exits 7 on a JS exception (since 0.1.6) and the description is on stderr.
- **Don't** write Promise-polling loops in `eval` for SPA waits. Use `wait --selector` / `--stable-ids` / `--network-idle` / `--js`. The `eval`-Promise pattern is a 0.1.x escape hatch.
- **Don't** `eval` `tab.keyboard.press` / `tab.mouse.click`. Use `keyboard press` / `mouse click`.
- **Don't** hand-roll `window.scrollTo(0, document.body.scrollHeight)` in `eval` for infinite scroll. Use `scroll --to-bottom --max-loops N --idle-ms M`.
- **Don't** drive 10 URLs sequentially with `get` when they're independent. Use `batch URL URL URL --query "..."`.
- **Don't** combine `--disable-images` with `network block -t Image`. The first turns image loading off via Chrome preferences; the second intercepts at the Fetch layer. Pick one — they overlap.
- **Don't** call `network block/mock/inject-header/fail` without `--session`. The interceptor needs to share the browser with the inner command, which only works through a persistent session.
- **Don't** conclude "no results" from a single short wait on an aggregator (Kayak/Expedia/Booking/Skyscanner). These sites return `0 of N` for tens of seconds before populating. Poll for stability (gotcha #12) before declaring a route empty.

## When this skill is installed from the pydoll-cli repo

See `AGENTS.md` in the repo for the full JSON-shape catalog per subcommand, attached-session patterns (`--connect`, `--fresh`, `--new-tab`), Wavebox specifics, and niche commands (`har record/replay`, `network logs`, `run SCRIPT.py`, `shell`). This skill covers the ~90% path; `AGENTS.md` is the reference for the rest.

Repository: https://github.com/dovidgefen/pydoll-cli
