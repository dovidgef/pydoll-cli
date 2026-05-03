# Changelog

All notable changes to pydoll-cli are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
