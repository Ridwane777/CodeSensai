# ADR-0017 — Web search: Chromium presents itself as a regular browser (user-agent)

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric Gbemetonou (Workstream B), after team feedback on the demo
- **Workstream**: B (`web_search` tool, browser sandbox). Complements [ADR-0014](0014-bing-search-engine.md), which is not modified.

## Context
After the switch to Bing (ADR-0014), the team found that `web_search`
responded but returned **0 results** for "Ollama tool calling API" and
"docker run read-only tmpfs", and off-topic results for
"python dataclass default factory". The same query made with `curl` returned
10 results.

Cause measured on 2026-10-14 (`sensai-browser` image, Chromium 155.0.8059.39,
query "Ollama tool calling API", number of `b_algo` occurrences in the dump):

| user-agent | `b_algo` |
| --- | --- |
| headless default (announces `HeadlessChrome`) | 0 |
| `Chrome/131.0.0.0` | 0 |
| `Chrome/155.0.0.0` (same version as the image's Chromium) | 83 |

Bing does not block openly: it serves a degraded page to anything that looks
like a bot, including a user-agent whose version does not match the real
engine.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. Change nothing | Zero code | `web_search` unusable in a demo |
| B. **`--user-agent` of a regular Chrome, at the image's Chromium version** | One line; measured: 10 results on the 3 queries; the rest of the sandbox is unchanged | Fragile (see ❌); imitates a browser |
| C. Search API (Brave Search API, self-hosted SearXNG) | Clear contract, no imitation | API key or service to deploy, hence another ADR; not tested here |

## Decision
Option B. `BrowserConfig.user_agent` (default:
`Mozilla/5.0 (X11; Linux x86_64) … Chrome/155.0.0.0 Safari/537.36`) is passed
to Chromium via `--user-agent=`. The network stays limited to `www.bing.com`,
JavaScript stays disabled by the image policy, the container stays disposable.

## Consequences
- ✅ Measured on 2026-10-14: 10 results for each of the three failing queries (about 4 s), no container left behind; the first result is the official documentation (docs.ollama.com, docs.python.org).
- ✅ Minimal change, covered by a test (`test_browser_presents_itself_as_a_regular_browser_not_headless`).
- ❌ **Coupled to the Chromium version**: with `Chrome/131` Bing still serves 0 results. If the image is rebuilt with another Chromium, `user_agent` must be aligned (`chromium --version`), otherwise the tool silently falls back to "0 results".
- ❌ **Fragile**: Bing can tighten its detection at any time; we imitate a browser instead of using a contract.
- ❌ **Terms of use**: posing as an ordinary browser aggravates the point already open in ADR-0014 (automated access without Microsoft's API). Acceptable for a demo, not for a product.
- ❌ The tool returns `ok: true` with 0 results when Bing serves a degraded page: the failure stays invisible to the model. Lead not handled here: treat "results page without `b_algo`" as `SearchEmptyPage`.
- Follow-up: if Bing blocks anyway, switch to Brave Search API or SearXNG (option C) through a new ADR.
