# Changelog

All notable changes to pydoll-cli are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Disk hygiene for session profiles, plus the groundwork for a public repo:
install moves to GitHub and CI finally covers the artifact users install.

### Added

- **`session prune`** — reclaim disk by deleting reclaimable profiles. Requires
  a selector: `--orphans` (profile dirs with no state file), `--dead`
  (registered sessions whose browser isn't alive), and/or `--older-than DAYS`.
  Supports `--dry-run` and `--yes`; never touches alive sessions; reports bytes
  reclaimed.
- **`session rm NAME…`** — stop a session if running, then delete its whole
  profile dir + state file.
- **`session list`** — now also surfaces leftover profile dirs as `orphan` rows
  (with size) so they're visible.

### Changed

- **`session stop` now deletes the session's on-disk profile by default**
  (owned sessions). Stopped sessions used to leave their full Chromium profile
  under `~/.cache/pydoll-cli/sessions/<name>/` forever — `stop` removed only the
  state file, so the leftovers were invisible to `list` and unreclaimable, and
  grew with every automation run. Pass `--no-purge` to keep the profile for a
  later `session start NAME` that reuses it (e.g. to preserve a login).
  Attached / shared-profile sessions own no profile dir, so their stop behavior
  is unchanged. The internal stale-session restart path never purges.
- **Install is from GitHub, not PyPI.** pydoll-cli was never published to PyPI,
  so the README's `pip install pydoll-cli` / `uv tool install pydoll-cli` lines
  could not work. Use
  `uv tool install git+https://github.com/dovidgef/pydoll-cli` (or the
  `pipx`/`pip` equivalent). The PyPI publish workflow is removed; a release is
  a git tag, and `git+…@vX.Y.Z` pins it.
- **The version is single-sourced from `pydoll_cli.__version__`.**
  `pyproject.toml` now derives it via hatch instead of repeating the literal,
  which is what let the two drift before.
- **A bare `pytest` no longer launches a browser.** Integration tests are
  deselected by default; run them with `pytest -m integration`.
- Upgraded pydoll 2.22.1 → 2.23.1. No CLI change was needed; verified with the
  unit suite and the browser-backed integration tests.
- CI additionally builds the sdist + wheel and smoke-tests the installed
  console script, which is the only place the `install-skill` force-include can
  be caught breaking. Browser-backed integration tests moved to their own
  manual-dispatch workflow.

### Fixed

- **Repository URLs pointed at a nonexistent `dovidgefen` account** in
  `pyproject.toml`, the README, and `SKILL.md`. The account is `dovidgef`.
- **The console help tests failed on CI and only on CI.** CI renders help in
  colour, and Rich's option highlighter styles a flag as two spans (`-` then
  `-level`), so the literal `--level` the tests looked for was never present in
  the output. The suite now pins Rich's colour and width, so help assertions
  check the text a user actually reads.
- The README's `extract --schema examples/quotes.json` example referenced a
  file that was not in the repo. Added `examples/quotes.json`.

## [0.4.2] — 2026-07-26

A dead session now says so instead of leaving a stray tab in your browser.

### Changed

- **Shared-profile attached sessions no longer spawn a replacement tab when
  the pinned tab is gone.** Recreating the tab is only free when we own the
  context it lives in: an incognito session's tab sits in a browser context
  pydoll-cli created, and `session stop` disposes that context wholesale, so
  that path still heals as before. A shared-profile session has no context of
  ours — the replacement landed in the user's real browser and outlived the
  session (`session stop` leaves it by default). Worse, it was silent and the
  command then ran against `about:blank`, so `eval` / `query` / `console logs`
  returned plausible empty answers instead of reporting a dead session.

  Now that case exits **6** with the two ways out: `--tab-url SUBSTR` (which
  re-pins the session to a live tab) or `session stop NAME` and start again.
  The same error covers an incognito session whose context died with the
  browser, where there is nothing left to heal into.

  This was the remaining half of the 0.3.2 blank-tab fix, which only covered
  calls that passed `--tab-url` / `--tab`. It shows up most after a browser
  restart: that invalidates every pinned target at once, so each stale session
  leaked one tab on its next call — while `session list` still reported them
  alive, since for attached sessions liveness only probes the WebSocket
  endpoint, never the pin.

## [0.4.1] — 2026-07-26

Retroactive console capture, and DevTools windows no longer hijack tab
selection.

### Added

- **`console` command group — read browser console output and JS errors.**
  `console logs` dumps the current document's console history and exits;
  `console watch` streams the same records as NDJSON until SIGINT or
  `--max-events`. Both merge three sources into one normalized record shape:
  `console.*` calls and uncaught exceptions (Runtime domain) plus
  browser-generated messages such as failed requests, CSP violations and
  deprecations (Log domain), which the `network` commands never surface.

  `console logs` is **retroactive**: Chrome buffers each document's console
  history (1000 entries, FIFO) and replays it to any client that enables the
  domains, so it works on a page some earlier invocation loaded — no prior
  arming, no daemon, no injected page shim. It returns as soon as the replay
  burst goes quiet (`--settle`, default 0.3s) rather than waiting out a fixed
  window; `--duration N` forces a fixed window when you also want to catch new
  output, and `--clear` discards the browser's history so the next read returns
  only what is new. Filters: `--level`, `--kind` (matched against the record
  source), `--filter` (substring on the message text). The default emits every
  level.
- **`--include-internal`** global flag — opt back into targeting
  browser-internal tabs.

### Fixed

- **A DevTools window no longer hijacks tab auto-selection.** DevTools is
  reported by CDP as a `page` target, so it passed pydoll's `get_opened_tabs`
  filter and could land at index 0 — making `--session NAME` calls without
  `--tab-url` drive `devtools://devtools/bundled/devtools_app.html` instead of
  the app. (pydoll's `Browser.connect` returns `get_opened_tabs()[0]`, so this
  hit every `--session` / `--connect` invocation that didn't name a tab.)
  `devtools://` and `chrome://` targets are now excluded everywhere the CLI
  picks or lists a tab — `tabs list` / `close` / `focus`, `--tab N`,
  `--tab-url`, the connect-time default tab, and the attached-session
  fallback — so `tabs list` indices stay in sync with what `--tab N` resolves
  to. Explicit selection still wins:
  `--tab-url devtools://` finds the DevTools target, and a session pinned to an
  internal tab by `target_id` keeps resolving. `--include-internal` restores the
  old behavior wholesale.

## [0.3.2] — 2026-05-05

Attached-session leak fixes + first-class "ride along on an existing tab" flow.

### Fixed

- **Attached + `--share-profile`: `session start --url X` no longer duplicates
  a tab.** When `X` matches an already-open tab in the running browser, that
  tab is adopted as-is (no re-navigation, no new tab). Previously a duplicate
  tab was always created.
- **Attached + `--share-profile`: blank-tab leak across `--session` calls.**
  When the pinned tab had been closed manually, every subsequent
  `pydoll-cli --session N --tab-url X …` invocation would spawn an
  `about:blank` tab in the user's browser before switching to the requested
  one. Now we skip the blank-tab fallback whenever the caller will resolve
  the tab via `--tab-url` / `--tab`, and re-pin `state.target_id` to the
  resolved tab so future calls hit it directly.

### Added

- **`session start --tab-url SUBSTR`** (with `--share-profile`). Adopt-only:
  pin an already-open tab whose URL contains the substring. Errors with
  exit 4 if no match — never spawns a tab. Use this when the user already
  has the target site open and you want the agent to ride along.
- **`session stop --close-tab`** (shared-profile mode). Also closes the
  pinned tab on stop. Pre-0.3.2 default.
- **`SessionState.created_target`** (`session info` output). `true` when the
  session created the pinned tab, `false` when it adopted an existing user
  tab.

### Changed

- **`session stop` (shared-profile mode) no longer closes the pinned tab by
  default.** Pass `--close-tab` for the previous behavior. Rationale: with
  the new adoption flows (smart `--url` reuse, explicit `--tab-url`), a stop
  could otherwise close a tab the user opened themselves.

## [0.3.1] — 2026-05-03

Bug-fix + small-ergonomic release surfaced by an end-to-end demo run of 0.3.0.

### Fixed

- **`mouse hover SELECTOR`.** The bound-script used the undefined identifier
  `argument` and lacked an explicit `return`, so every hover failed with
  `hover: failed to read element bounds`. Now uses `element.execute_script`
  with `this` and an explicit `return [cx, cy]`.
- **`network watch --max-events N`.** Could overshoot the cap because the
  emit closure decided the cap *after* writing — handler invocations that
  raced past the limit kept emitting. Now gates emission on the counter at
  the top of `_emit`, so the cap is exact.
- **`wait --page-event load|dom-content` race on already-fired events.**
  `LoadEventFired` / `DomContentEventFired` are *next-event* signals; a
  fresh listener after the page already finished loading would hang for the
  next nav that never came. Pre-checks `document.readyState` and resolves
  immediately when the page is already past the milestone (returns
  `{"event": "load", "already": "complete"}`). `frame-navigated` is unchanged
  — it remains a "next navigation" listener.

### Added

- **`text --selector S --all`.** Returns text from every match instead of
  just the first one. JSON shape switches from `{"text": "..."}` to
  `{"texts": [...], "count": N}`. Without `--all`, behavior is unchanged.

### Documentation (Claude Code skill)

`SKILL.md` gap-closure based on the same demo run:

- `request` runs as `fetch()` from the current tab's page context, so the
  page's CSP applies. Strict `connect-src` (HN, GitHub, etc.) blocks
  cross-origin fetches with `TypeError: Failed to fetch` even when the
  target accepts CORS — workaround: navigate to a permissive page first
  (`example.com`); cookies for the target host follow the target host's
  jar, so the detour costs no auth.
- `network mock` cross-origin must include `Access-Control-Allow-Origin`
  in the response headers — the browser still CORS-checks fulfilled
  responses, so the synthetic body bounces with `TypeError: Failed to fetch`
  otherwise. Same-origin mocks don't need it.
- `tabs new --url ...` does not auto-focus. Subsequent `--session NAME`
  calls without `--tab N` / `--tab-url SUBSTR` keep targeting the previous
  tab; pin with `--tab-url` (stable across the session) per call.
- `screenshot --full-page` first-call hang on Chrome 146 with
  `--page-load-state interactive` — the renderer hasn't laid out content
  beyond the viewport yet. Wait for `document.readyState === 'complete'`
  before the capture.
- **Headless + bot-protected sites: spoof the UA at session-start.**
  Headless Chrome's default User-Agent contains the literal token
  `HeadlessChrome/...`, which heavily-protected destinations match in a
  one-line check. Fix: `--user-agent` global flag with a clean current
  Chrome desktop UA. Headed mode strips the token automatically.

### Tests

- 3 new unit tests for `wait --page-event` auto-resolve (load on `complete`,
  dom-content on `interactive`, fall-through to listener when `loading`).
- 177 → 180 passing.

## [0.3.0] — 2026-05-03

The network-interception release. Four new `network` subcommands wrap CDP's
Fetch domain so an agent can block, mock, or fail requests for the duration
of an inner command — the testing-side complement to `request`.

### Added

- **`network block -t TYPE [-t TYPE...] -- CMD ARGS`.** Block matching
  resource types (`Image`, `Stylesheet`, `Font`, `Script`, `Media`, `XHR`,
  `Fetch`, `Document`, `WebSocket`, `Manifest`, `Ping`, `Other`,
  case-insensitive) for the inner command's lifetime. Calls
  `fail_request(BLOCKED_BY_CLIENT)` on matches; `continue_request` on
  everything else. Typical 2× speedup for screenshotting image-heavy pages
  with `-t Image -t Stylesheet -t Font`.
- **`network mock -p URL_SUBSTR --status N --body FILE [-H "K: V"]
  -- CMD ARGS`.** Fulfill matching requests with a canned response. Body
  bytes are base64-encoded for the CDP wire format. Matching is substring
  on the request URL.
- **`network inject-header -p URL_SUBSTR -H "K: V" [-H "K: V"...] -- CMD
  ARGS`.** Merge extra request headers into matching requests
  (`continue_request` with combined headers; new wins on collision).
- **`network fail -p URL_SUBSTR [--reason ERR] -- CMD ARGS`.** Fail matching
  requests with a CDP `ErrorReason` (default `TIMED_OUT`; useful values:
  `FAILED`, `ABORTED`, `CONNECTION_REFUSED`, `NAME_NOT_RESOLVED`,
  `BLOCKED_BY_CLIENT`).

### Architectural notes

- **Wrap pattern via subprocess.** All four commands require `--session
  NAME` (or `--connect WS_URL`). The wrapping command opens a tab, enables
  Fetch, registers the handler, then spawns the inner command as a
  subprocess that connects to the same session. When the subprocess exits,
  Fetch is disabled and the wrapper exits with the subprocess's return
  code. This was the plan's option (a); option (b) — persistent session
  interceptors stored in `~/.cache/pydoll-cli/sessions/<NAME>.json` — is
  deferred until usage demand justifies the state-sync complexity.
- The conventional `--` separator between the wrapping options and the
  inner command is supported but not required (the wrapping command parses
  with `allow_extra_args=True, ignore_unknown_options=True`).

### Changed

- **SKILL.md** gains gotcha #20 (network interception): wrap-pattern usage,
  the four subcommands, when each is the right tool, the typical 2×
  page-load speedup with `block`. Anti-patterns list grows: don't pair
  `--disable-images` with `network block -t Image`; don't call interceptors
  without a `--session`.
- **CHANGELOG / README / AGENTS.md** updated with new commands and JSON
  shapes (interceptor stdout is whatever the inner command emits).

## [0.2.0] — 2026-05-03

The SPA-hydration release. Closes the largest functionality gap in 0.1.x:
agents had to roll Promise-polling loops in `eval` to wait for SPAs to
render. Now there's a first-class `wait` command with selector / network-idle
/ URL / page-event / JS / stable-ids modes, plus the keyboard / mouse /
scroll / upload / batch primitives the CLI was missing.

### Added

- **`wait` command (centerpiece).** One flat command with mutually-exclusive
  modes: `--selector S [--count N]`, `--network-idle [--idle-ms 500]
  [--max-inflight 0]`, `--url-contains STR`, `--page-event {load,dom-content,
  frame-navigated}`, `--js EXPR`, `--stable-ids "SELECTOR|ATTR" [--stable-ms
  2000]`. Shared `--wait N` overall timeout. Output `{"ready": true, "ms": N,
  "matched": …}`; exits **3** on timeout. The `--stable-ids` mode is the
  recommended pattern for aggregator sites (Kayak/Expedia/Booking) where
  results progressively populate.
- **`get URL --wait-for SELECTOR --wait N`.** Combine navigation and wait in
  one round-trip. Exits **4** if the selector never appears.
- **`--page-load-state {complete,interactive}` global flag.** Maps to pydoll
  `PageLoadState`. `interactive` (DOMContentLoaded) returns ~2–5× faster on
  JS-heavy pages than the default `complete` (full load event). Pair with
  `wait --selector` for SPA work.
- **`--webrtc-leak-protection` global flag.** Enables pydoll's WebRTC
  suppression — closes the IP-leak side-channel that bypasses the HTTP proxy.
- **`keyboard` group.** `press KEY [--modifiers M[,M]] [--interval-ms N]`,
  `hotkey K1 K2 [K3]` (max 3 keys per pydoll), `down KEY` / `up KEY`,
  `type "text" [--humanize]`. CLI accepts both `CONTROL` and `CTRL` (and
  `CMD`/`META`, `OPT`/`ALT`).
- **`mouse` group.** `move X Y`, `click X Y [--button B] [--double]`,
  `drag X1 Y1 X2 Y2`, `hover SELECTOR`. All accept `--humanize` for curved
  cursor paths.
- **`scroll` command.** `--by-y N` (negative = up), `--to-y N` (absolute, via
  `window.scrollTo`), `--to-bottom [--max-loops N] [--idle-ms M]` (loops on
  infinite-scroll pages until `scrollHeight` stops growing), `--to-selector S`
  (uses `element.scroll_into_view`). All accept `--humanize`.
- **`upload SELECTOR FILE [FILE...]`.** Default mode calls
  `element.set_input_files`. With `--via-chooser`, SELECTOR is a button and
  the CLI clicks it inside an `expect_file_chooser()` context.
- **`batch URL [URL...]`.** Parallel multi-tab driver via `asyncio.gather`.
  Flags: `--screenshot-dir DIR`, `--source-dir DIR`, `--query SELECTOR`,
  `--concurrency N` (default min(num URLs, 10)). One JSON record per URL.
- **`network watch`.** Streaming NDJSON variant of `network logs` — emits one
  event per line as they happen. Runs until SIGINT or `--max-events N`. Flags:
  `--kind {request,response,both}`, `--filter SUBSTR`.
- **`cloudflare auto-solve [--duration N]`.** Long-running auto-solver.
  Pair with `--session NAME`: this command keeps the captcha callback
  registered while *another* CLI invocation drives the same browser.
- **Internal helper:** `wait_for_event(tab, event_name, *, predicate, timeout)`
  in `async_runner.py` — generic CDP event subscription for any future
  event-driven command.

### Changed

- **SKILL.md substantially rewritten.** Gotcha #12 (SPA hydration) replaces
  the long Promise-polling examples with a decision tree pointing at the
  right `wait` mode for each scenario. Five new gotchas: #15 (iframe
  auto-split), #16 (actionability gap — pydoll waits for presence, not
  visibility/enablement), #17 (use the new `mouse`/`keyboard`/`scroll`
  commands instead of `eval`), #18 (`batch` for parallel scraping), #19
  (`upload` modes). Quick-reference table extended with the 0.2.0 commands.
  Anti-patterns list updated.
- **README** feature-overview table reflects new commands and global flags;
  Quick-start gains SPA / `wait` / `batch` examples.
- **AGENTS.md** JSON-shape catalog gains entries for every new command.

### Notes

- `wait --network-idle` is implemented via Network domain event subscription
  with an in-flight set and configurable idle window. Per Playwright's
  documented stance, `networkidle` is discouraged when a selector signal is
  available — use `--selector` or `--stable-ids` first.
- `keyboard.hotkey` accepts at most 3 keys per pydoll's API.
- `cloudflare auto-solve start`/`stop` was originally planned as two
  subcommands. Reduced to a single blocking `auto-solve` because the CLI's
  per-invocation lifetime would invalidate the start/stop split (callbacks
  die when the process exits).
- `--pre-click-delay` (planned for 0.1.6) was skipped; pydoll 2.22 ignores
  the underlying `time_before_click` parameter.

## [0.1.6] — 2026-05-03

P0 bug fixes — every CLI flag now does what its `--help` says.

### Fixed

- **`click --human` now humanizes the click.** Previously `--human` (the
  default) called raw CDP `element.click()` (no humanization) — only `--fast`
  was distinct. Now `--human` passes `humanize=True` so you get the full
  pydoll cursor curve; `--fast` keeps the raw JS click. Behavior change for
  existing scripts that relied on the old (silently-raw) default.
- **`type --human` now humanizes the typing.** Previously `--human` passed
  `interval=delay_ms/1000` (constant cadence) — not real humanization. Now
  `--human` invokes pydoll's variable-timing humanization (~2% realistic
  typos, punctuation pauses); `--delay-ms N` is a separate constant-cadence
  mode (only takes effect when explicitly set).
- **`eval --script` awaits Promises.** Now passes `await_promise=True` to CDP,
  so async one-liners (`(async () => …)()`) and Promise-returning scripts
  resolve correctly without manually wrapping in `setTimeout` polls.
- **`eval --script` exits 7 on JS error.** Previously a JS exception silently
  exited 0 with `{value: {subtype: "error", …}}` — exit-code-driven shell
  scripts couldn't tell. Now exit code is `7` (new `EXIT_JS_ERROR`) and the
  description is written to stderr as `error: JS error: …`.
- **`eval` result extraction is shape-tolerant.** A defensive helper now
  handles both wrapped (`{result: {result: RemoteObject}}`) and unwrapped
  (`{result: RemoteObject}`) response shapes from `tab.execute_script`.

### Added

- **`--proxy-insecure` global flag.** Appends `--ignore-certificate-errors`
  for authenticated proxies (Bright Data, etc.) that present an internal CA
  cert. Use instead of `-a --ignore-certificate-errors`.
- **`cloudflare bypass --captcha-timeout SECONDS`** (default 5). Maps to
  pydoll's `time_to_wait_captcha`. Increase when the bypass returns but the
  page is still on the challenge.
- **`network logs --full/--slim`** (default `--slim`). `--full` emits the
  entire CDP `params` dict per record (type, headers, timestamps, initiator,
  …); `--slim` keeps the existing `{url, method, request_id}` shape.
- **`install-skill` command.** Drops the bundled Claude Code skill into
  `./.claude/skills/pydoll-cli/SKILL.md` (project scope, default) or
  `~/.claude/skills/pydoll-cli/SKILL.md` (`--scope user`). The skill ships
  inside the wheel via a hatchling `force-include` rule, so `pip` / `uv tool`
  / `pipx` users get it without cloning the repo. Pass `--target DIR` for an
  explicit destination, `--force` to overwrite an existing copy.

### Changed

- **Exit code table** gains `7` (`EXIT_JS_ERROR`). README, AGENTS.md, SKILL.md
  all updated.
- **Skill (SKILL.md)** updated: gotcha #11 rewritten around exit 7 (drop the
  `jq -e '.value.subtype == "error"'` workaround); click/type quick-reference
  rows clarified; cloudflare gotcha mentions `--captcha-timeout`; anti-pattern
  list mentions `--proxy-insecure` over hand-rolled `--ignore-certificate-errors`.
- **README** Quick-start example for `--no-headless` now puts the global flag
  before the subcommand (`pydoll-cli --no-headless session start …`).

### Notes

- pydoll's `time_before_click` parameter on `expect_and_bypass_cloudflare_captcha`
  is deprecated and ignored as of pydoll-python 2.22, so no `--pre-click-delay`
  flag was added — it would have been a no-op exactly the kind of misleading
  flag this release is fixing.

## [0.1.5] — earlier

See `git log v0.1.4..v0.1.5` for details.

## [0.1.4] — earlier

`--no-sandbox` made opt-in via `--in-container`.

## [0.1.3] — earlier

Attached sessions with incognito + shared-profile modes.
