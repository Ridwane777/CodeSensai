# T3 — Web search: real engine trials

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: isolated web search: ✅ `python.org` with both models, qwen3:8b on CPU 11 min 16, qwen3-coder:30b on GPU 10 s. Earlier measurements below.

Measurements of 2026-10-24, Linux machine (local Docker, `sensai-browser`
image), agent on the RunPod pod (`qwen3-coder:30b`). Decision:
[ADR-0040](../decisions/0040-duckduckgo-web-search-with-bing-fallback.md).
Each query is measured once: these are orders of magnitude.

## Why change: Bing only answered on the first word

`web_search` tool called directly, original image (Bing only):

| Query | Top three results |
| --- | --- |
| `python asyncio gather example` | python.org, python.org/downloads, online-python.com |
| `ollama tool calling activation` | ollama.com, ollama.com/download/windows, github.com/ollama/ollama |
| `Ollama tool calling official documentation` | identical to the previous row (all 10) |
| `tool calling ollama docs` | no results |

The returned page does contain the full query (page title, search field):
Bing receives it, but serves a degraded page to the automated browser. In the
full trial the same day, the agent answered "I found no official
documentation" three times out of three.

## After: DuckDuckGo HTML, Bing as fallback

Image rebuilt (`docker build -t sensai-browser:latest docker/browser`), tool
called directly:

| Query | Duration | Top three results |
| --- | --- | --- |
| `ollama tool calling activation` | 5.1 s | docs.ollama.com/capabilities/tool-calling, deepwiki.com/…/tool-calling, ollama.com/blog/tool-support |
| `Ollama tool calling official documentation` | 4.5 s | docs.ollama.com/capabilities/tool-calling, docs.ollama.com/index, lzw.me/…/tool-calling |
| `python asyncio gather example` | 4.7 s | pythontutorial.net/…/python-asyncio-gather, superfastpython.com/asyncio-gather, slingacademy.com/…/gather |
| `fastapi streaming response sse` | 5.1 s | fastapi.tiangolo.com/tutorial/server-sent-events, fastapi.tiangolo.com/reference/sse, devdojo.com/…/sse-with-fastapi |
| `comment configurer pytest pour un projet python` (French query) | 5.3 s | adamcours.fr/…/pytest, fr.w3docs.com/…/python-pytest, pasclairpython.fr/…/pytest |

Through the agent (real CLI, pod): "Search the web for Ollama's official
documentation on tool calling" → one `web_search` call, 10 results, and the
answer cites `docs.ollama.com/capabilities/tool-calling` (21.5 s for the
turn).

The Bing fallback is checked by the tests (blocked page, empty page, no
results, shared time budget), not on the real site: DuckDuckGo did not block
from this network during the trial.

## Limits

- One measurement per query, a single network.
- The Bing fallback currently gives poor results (first word only).
- Both engines are parsed as HTML: a markup change can empty the results
  without an error (tests on saved pages).
