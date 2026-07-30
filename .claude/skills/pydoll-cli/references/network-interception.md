# Network interception: block / mock / inject-header / fail

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

`network mock` is the testing-side complement to `request` (SKILL.md gotcha #14): when you want to drive the page but stub the API.

**Cross-origin mocks need `Access-Control-Allow-Origin`.** The browser still CORS-checks fulfilled responses, so a mock for a host different from the page's origin must include the header or the inner `fetch()` (or `request`) fails with `TypeError: Failed to fetch`:
```bash
pydoll-cli --session s network mock -p /api/me --status 200 --body fixture.json \
  -H 'content-type: application/json' \
  -H 'access-control-allow-origin: *' \
  -- request GET https://api.other-host.com/api/me
```
Same-origin mocks (page is on `app.com`, mocking `app.com/api/...`) don't need it.

The `--` separator is conventional but not required — the wrapping command captures everything after the recognized options as the inner command.

## Anti-patterns

- **Don't** conclude `network block` is broken when a page you already visited in this session still renders styled. Fetch interception never sees a request the HTTP cache serves, so blocking looks like a no-op on warm assets. Verify on a fresh session (or a URL the session hasn't loaded); `getComputedStyle(document.body).backgroundColor` going transparent and `document.images[0].naturalWidth === 0` are the reliable signals — `document.styleSheets.length` is not, since a blocked `<link>` still counts.
- **Don't** combine `--disable-images` with `network block -t Image`. The first turns image loading off via Chrome preferences; the second intercepts at the Fetch layer. Pick one — they overlap.
