# ADR-0040 — Web search: DuckDuckGo HTML first, Bing as fallback

- **Status**: Accepted (2026-10-24); supersedes [ADR-0014](0014-bing-search-engine.md)
- **Date**: 2026-10-24
- **Deciders**: Ridwane (Workstream C) and Meric (Workstream B)
- **Workstream**: B (`execution/sandbox/`, `docker/browser` image). Changes neither the `web_search` tool interface nor its contract.

## Context

[ADR-0014](0014-bing-search-engine.md) replaced DuckDuckGo with Bing
on 2026-10-14: DuckDuckGo was serving an anti-bot challenge (HTTP 202,
"anomaly" page) to the development network. It noted two ❌: "fragile by
nature" and "no fallback engine".

Full trial run of 2026-10-24: the agent could not find Ollama's
documentation on tool calling. Direct measurement, same image, same day:

| Query | Bing: top results |
| --- | --- |
| `python asyncio gather example` | python.org, python.org/downloads, online-python.com, w3schools… |
| `ollama tool calling activation` | ollama.com, ollama.com/download/windows, github.com/ollama… |
| `Ollama tool calling official documentation` | **the same 10 results** as the previous line |

Bing does receive the whole query (it appears in the page title and
in the search field) but only answers on the **first word**. It is
a degraded page served to the automated browser, not a code defect.

Same day, DuckDuckGo HTML (test image that only allows
`html.duckduckgo.com`): 4 queries out of 4 with relevant results, including
`docs.ollama.com/capabilities/tool-calling` first for both Ollama
queries, and the FastAPI SSE documentation for "fastapi streaming
response sse". No anti-bot challenge from this network.

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| A. Keep Bing alone | Nothing to change | Measured: results on the first word only; the tool is useless in a demo |
| B. DuckDuckGo HTML alone | Measured: relevant (4/4); page made for browsers without JavaScript; better privacy | Blocked on another network on 2026-10-14: we would fall into the same trap |
| C. **DuckDuckGo HTML first, Bing as fallback** (same container, same time budget) | Relevant when DuckDuckGo answers; the tool still works if DuckDuckGo blocks or finds nothing; no key | Two HTML pages to track instead of one; if DuckDuckGo blocks, we fall back to Bing's degraded page; the container can reach two hosts instead of one |
| D. Search API (Brave Search API) or self-hosted SearXNG | Clear contract, no more page parsing | API key (secret, quota, cost) or a service to deploy; not measured here |

## Decision

Option C. `BrowserConfig.search_hosts = ("html.duckduckgo.com", "www.bing.com")`.
`BrowserSandbox.search` tries each engine in order and keeps the first
that returns results. It moves to the next if the page is blocked, empty,
unexpected, unreachable or has no results; it does not if the image
is missing, Docker is down or the query is invalid (the second engine
would fail the same way). Both attempts share the same time
budget (25 s by default, 45 s at most); the fallback only starts if at
least 5 s remain.

Confinement unchanged in principle: Chromium's resolver and the
image policy only allow these two hosts, JavaScript stays off,
the container stays disposable. The engine is recognized from the page itself
(`result__a` for DuckDuckGo, `b_algo` for Bing); redirect links
from both engines are decoded to the host and their internal links discarded.

## Consequences

- ✅ Relevant results when DuckDuckGo answers (measurements in
  [web-search.md](../performance/web-search.md)).
- ✅ A fallback engine: a DuckDuckGo block no longer silences the tool.
- ✅ Still no key or secret; the query goes to DuckDuckGo first,
  more privacy-protective than Microsoft.
- ❌ Two HTML pages to track: if one changes, its results disappear
  without an error (tests on saved pages, not on the live sites).
- ❌ The Bing fallback currently gives poor results (first word
  only): better than nothing, not a real backup.
- ❌ The container can reach two hosts instead of one (still no other).
- ❌ Terms of service: as with Bing, automated access to
  DuckDuckGo is not a guaranteed use; occasional use by a non-commercial
  project (see `docs/legal/`).
- Follow-up: if both engines block or degrade, move to option D
  behind the same `BrowserSandbox`; rebuild the image
  (`docker build -t sensai-browser:latest docker/browser`) after this
  change, the old one only allows Bing.
