# Changelog

All notable changes to pydoll-cli are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
