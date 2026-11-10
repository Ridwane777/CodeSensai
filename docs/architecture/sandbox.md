# Sandbox: running code and searching the web in disposable containers

Feature [T2]. Decisions: [ADR-0012](../decisions/0012-docker-chromium-sandbox.md), search engine:
[ADR-0014](../decisions/0014-bing-search-engine.md) (Bing), then
[ADR-0040](../decisions/0040-duckduckgo-web-search-with-bing-fallback.md) (DuckDuckGo HTML first, Bing as fallback).
Tool contract the two tools follow: [tool-contract.md](tool-contract.md).

The agent has two ways to touch the outside world, and they are kept apart:

| | `run_code` | `web_search` | Documents (`read_file`, RAG) |
|---|---|---|---|
| What it does | Runs Python the model wrote | Searches the web, returns title / URL / snippet | Converts one PDF / Office / EPUB file to Markdown (MarkItDown) |
| Container image | `python:3.12-slim` | `sensai-browser` (Debian + Chromium), built locally | `sensai-docs` (Python + MarkItDown 0.1.8, 659 MB), built locally |
| Network | **None** | Outbound only; can resolve one host (the search engine) | **None** |
| Risk level | `execute`: always asks the user first | `network`: runs, unless preferences say `ask` | `read` (the document is the user's own project file) |
| Code | `execution/sandbox/python_sandbox.py`, `tools/sandbox_tool.py` | `execution/sandbox/browser_sandbox.py`, `tools/web_search_tool.py` | `execution/sandbox/document_sandbox.py`, `docker/docs/` (ADR-0034) |

Code that runs never has network, and the browser never runs the model's code.
Neither container sees a file, a variable or a secret of the host. The
document container sees exactly one file, the document, mounted read-only,
and runs as the host user so that a file readable only by its owner can be
converted. Build it once: `docker build -t sensai-docs:latest docker/docs`.

```
model ─► ToolGateway ─► SandboxTool ─► PythonSandbox ─► container (no network) ─► stdout / traceback
                    └─► WebSearchTool ─► BrowserSandbox ─► container (Chromium) ─► page dump
                                                              │
                                      parsed on the host into plain, bounded strings
```

The gateway still applies everything in the tool contract on top: schema
validation, confirmation (A3), credential masking (EV2), sanitizing, size cap.
The sandboxes only produce data.

## `run_code`

Each call starts a new container and removes it afterwards, even after an error.

| Restriction | Setting |
|---|---|
| Network | none (`network_mode=none`) |
| Filesystem | read-only root, 16 MB `/tmp` (`noexec`) |
| User | uid 65534, all capabilities dropped, `no-new-privileges` |
| Memory | 256 MB, swap equal (no swap) |
| CPU / processes | 0.5 CPU, 64 processes |
| Host files | no volume, no socket |
| Time | 10 s by default, 60 s at most, container killed on timeout |
| Code size | 100 KB; the code is passed as an argument, not as a file |
| Output | 64 KB per stream; Docker log capped at 4 MB |

The result carries `ok`, `exit_code`, `stdout`, `stderr`, `traceback`,
`error_type`, `error_message`, `timed_out`, `oom_killed`, `duration_s`,
`truncated`. When the code fails the tool returns `ok=False` with the error and
the traceback in `content`, which is what lets the model fix its code and retry.
The retry loop belongs to the agent (Lot A), not to the sandbox.

If Docker is unavailable the tool returns an error of type `SandboxError`; it
never raises.

## `web_search`

Why a container: a search page is hostile input read by a very large engine. If
Chromium is exploited, the attacker lands in a disposable, unprivileged,
read-only container that holds nothing.

Each search starts a new container (user 65534, no capabilities, read-only root,
no volume, 768 MB, 1 CPU, 256 processes, 45 s at most) and removes it afterwards.
Four layers limit what the browser can do, outermost first:

1. **Container hardening**, as above.
2. **Name resolution**: `--host-resolver-rules="MAP * ~NOTFOUND , EXCLUDE <search host>"`.
   Every name except the search engine fails to resolve, so a redirect to an
   internal host name goes nowhere.
3. **Browser policy** baked into the image (`/etc/chromium/policies/managed`):
   every URL is blocked except the two search hosts (`html.duckduckgo.com`,
   `www.bing.com`), no downloads,
   no JavaScript. JavaScript is switched off by this policy only: the
   `--blink-settings=scriptEnabled=false` flag makes `--dump-dom` print nothing.
4. **Parsing**: the page dump is read on the host with the standard library
   parser and reduced to at most 10 results of plain, bounded strings. The page
   itself is never shown to the model.

Only snippets come back. Opening a result page is a separate, riskier capability
and is not part of this tool.

### Build the image

```
docker build -t sensai-browser:latest docker/browser
```

The image is about 1 GB. Without it `web_search` fails cleanly with
`ImageMissing` and the command above in the message. It is built locally, never
pulled, so no registry has to be trusted.

### What the browser container does not protect against

Be aware of these; none is hidden by the layers above.

- **Chromium runs with `--no-sandbox`.** Its own sandbox needs kernel features
  that Docker's default profile removes. The container takes its place. A
  Chromium exploit plus a container escape would reach the host; this is why the
  container is unprivileged, has no capabilities and is disposable.
- **The container has outbound network.** The resolver rule and the policy do
  not cover URLs written as IP addresses, and JavaScript being off removes most
  but not all ways for a page to trigger a request. The Docker bridge can also
  reach the host's LAN. Hardening that needs root and is not done here: block
  private ranges for the Docker bridge, for example

  ```
  iptables -I DOCKER-USER -s 172.17.0.0/16 -d 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16 -j DROP
  ```

  (adapt the subnets to the machine).
- **The search engine can refuse or change.** The tool reads the HTML of
  `https://html.duckduckgo.com/html/?q=...` first, then of
  `https://www.bing.com/search?q=...` if DuckDuckGo blocks, returns an empty or
  unexpected page, or finds nothing (ADR-0040; both tries share one time
  budget). On 2026-10-24 Bing answered on the first word of the query only;
  DuckDuckGo had been blocked on another network on 2026-10-14 (ADR-0014).
  DuckDuckGo result links are `//duckduckgo.com/l/?uddg=<URL>` redirects, decoded
  on the host, and its ads (`result--ad`) are dropped. Chromium is started with `--user-agent=` set to a
  regular Chrome whose version matches the image's Chromium (ADR-0017): with the
  default `HeadlessChrome`, or a mismatched version, Bing serves 0 results.
  Result links
  are Bing redirects (`/ck/a?...&u=a1<base64url>`), decoded on the host; links
  to Bing itself are dropped. Bing's terms restrict automated access and the
  page layout can change without notice: the parser relies on `b_results`,
  `b_algo`, `b_caption` and is tested against a saved page
  (`tests/execution/sandbox/fixtures/`), not against the live site. A layout
  change can look like "no results".
- **Failures are told apart**, so the model and the user see the real cause:

  | `error_type` | Meaning |
  |---|---|
  | `SearchBlocked` | Bot protection (captcha, challenge) instead of results |
  | `SearchEmptyPage` | The browser dumped an empty page (bot challenge, JavaScript-only page) |
  | `SearchUnavailable` | Chromium error page: Bing could not be reached from the sandbox |
  | `SearchUnexpectedPage` | A page that is neither a results page nor an error page |

  A results page with no result is a success with an empty list.
- **Queries go to Microsoft.** The query leaves the machine and can be linked to
  its IP address. Do not search for anything confidential.
- **Results are untrusted text.** The gateway removes hidden characters and logs
  injection-like text, and the agent must fence results as data. Nothing makes a
  hostile snippet harmless to a model that decides to obey it; that is what
  `confirm_after_untrusted` is for.

## Tests

- `pytest -m "not docker"` runs everything with a fake Docker client.
- `pytest -m docker` runs the isolation tests on real containers
  (`python:3.12-slim`): no network, read-only root, unprivileged user, memory and
  process limits, host files invisible, timeout, output cap. They skip when no
  Docker daemon answers, and fail if a container is left behind.
- There is no automated test that starts Chromium or reaches a search engine:
  the image is large and the site is external. After building the image, check
  once by hand: `docker run --rm sensai-browser:latest chromium --version`, then
  a live search:
  `python -c "from sensai.execution.sandbox.browser_sandbox import BrowserSandbox; print(BrowserSandbox().search('python asyncio'))"`
  (10 results with external URLs and snippets expected).
