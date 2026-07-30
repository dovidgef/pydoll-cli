# Attached sessions: driving the user's logged-in Chrome

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

**A session whose pinned tab was closed exits 6.** `session list` is not proof a session is usable — for attached sessions it only checks that the browser's WebSocket answers, never that the pinned tab still exists. A browser restart invalidates every pin at once, so a long-lived session can read "alive" and still be dead. In shared-profile mode pydoll-cli will *not* open a replacement tab (that would leave a stray `about:blank` in the user's real browser and silently run your command against it); it errors instead. Two ways out:
```bash
pydoll-cli --session s --tab-url 'app.com' --output json query 'h1'   # re-pins to a live tab
pydoll-cli session stop s && pydoll-cli --browser wavebox --output json session start s --share-profile --tab-url 'app.com'
```
Incognito sessions still self-heal — that tab lives in a context pydoll-cli owns and `session stop` disposes it.

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
