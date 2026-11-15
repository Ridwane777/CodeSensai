# ADR-0014 - Web search engine: Bing (HTML page) instead of DuckDuckGo

- **Status**: Superseded by [ADR-0040](0040-duckduckgo-web-search-with-bing-fallback.md)
- **Date**: 2026-10-14
- **Deciders**: Meric Gbemetonou (Workstream B), after observation on the development machine
- **Workstream**: B (`web_search` tool, browser sandbox). Changes neither the tool's interface nor its contract.

## Context
The `web_search` tool ([ADR-0012 sandbox](0012-docker-chromium-sandbox.md))
reads a search engine's results page with Chromium in a disposable
container, then extracts title, URL and snippet. The initial engine was
DuckDuckGo (`html.duckduckgo.com/html/`).

Observation on 2026-10-14, from the development network: DuckDuckGo answers
**HTTP 202 with an "anomaly" page (anti-bot challenge)** instead of the
results. Result on the tool side: an empty dump or a challenge page, and a
"the engine could not be reached" message that hid the real cause. The
engine blocks this network; it is not a parser bug.

Measured the same day with Bing: `curl` and Chromium (in the project image)
receive a results page with 10 `<li class="b_algo">`.

Another observation, independent of the engine: with
`--blink-settings=scriptEnabled=false`, `chromium --dump-dom` outputs
**nothing** (measured on Bing). JavaScript stays disabled by the image's
enterprise policy (`"JavascriptEnabled": false`, checked with a test page
whose script does not run); the flag is removed from the command line.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. DuckDuckGo `/html/` (status quo) | No account, good privacy image | **Blocked here** (HTTP 202, anti-bot challenge); nothing guarantees it works on the demo network |
| B. DuckDuckGo "lite" | Simpler page | Same provider, likely same anti-bot; not tested |
| C. **Bing, HTML page** (`www.bing.com/search?q=`) | Tested: results served to `curl` and Chromium; no key, no secret; stable structure (`b_algo`, `b_caption`) | Parsing a page, not an API; redirect links to decode; terms of use (see ❌) |
| D. Brave Search (HTML page) | Independent index | Not tested; anti-bot protections unknown |
| E. Self-hosted SearXNG | No per-engine blocking, aggregates several sources | One more service to deploy and maintain; it queries engines itself, which may block it |
| F. Paid Bing API | Clear contract, no scraping | API key (secret), quota and cost; offer to re-check; outside the "no paid service" scope |

Only A and C were tested on the machine. B, D, E and F were rejected on
reading, not on measurement.

## Decision
Option C. The tool queries `https://www.bing.com/search?q=<query>`. The
browser only resolves and opens `www.bing.com` (`search_host` setting,
Chromium resolver and image policy aligned). Bing result links
(`/ck/a?…&u=a1<base64url>`) are decoded on the host; links internal to Bing
are discarded. Blocked, empty or unexpected pages are reported with a
specific error code (`SearchBlocked`, `SearchEmptyPage`,
`SearchUnavailable`, `SearchUnexpectedPage`) instead of a single
"unreachable".

## Consequences
- ✅ `web_search` works on the development machine: 10 results for "python asyncio" during the live test of 2026-10-14 (a single measurement, about 4 s).
- ✅ Still no API key or secret; the container's exposed surface remains a single host.
- ✅ Failures tell the model and the user the real cause (blocked page, empty page, network down, unexpected page); each case is tested.
- ❌ **Fragile by nature**: we read Bing's HTML, which can change without notice. The parser relies on three structural markers (`b_results`, `b_algo`, `b_caption`) and on the `u=a1…` link format; if one changes, the tool may return "no results" without an error. Tests run on a recorded page, not on the real site.
- ❌ **Terms of use**: Microsoft's terms in principle limit automated access to Bing outside the API. Occasional use by a non-commercial project, but not a guaranteed use; to be reviewed before any commercial use (see `docs/legal/`).
- ❌ **Less privacy than DuckDuckGo**: the query goes to Microsoft, which can link it to the IP address. Put nothing confidential in a search.
- ❌ Bing may also present an anti-bot challenge from another network; the tool would report it (`SearchBlocked`) but has no fallback engine.
- Follow-up: tests `tests/execution/sandbox/test_search_parsing.py` (page recorded on 2026-10-14) and `test_browser_sandbox.py`. To revisit if Bing changes its markup or blocks the tool: switch to a self-hosted SearXNG (E) or an API (F), behind the same `BrowserSandbox`/`search_parsing`.
