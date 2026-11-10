# Real web interface: end-to-end trial

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: web scenarios through `sensai-web`'s API: X1 streamed turn ✅ (qwen3:8b 9 min 04, qwen3-coder:30b 7 s), X4 form ✅, X2 fork ✅, X3 export and share ✅, EV3 log ✅; A3 approval through `/confirm` ✅ with qwen3:8b, 2 of 4 with qwen3-coder:30b (backlog #26). Earlier measurements below.

Decision: [ADR-0035](../decisions/0035-real-web-server.md).

**Method** (2026-10-18). `sensai-web` started on a small test project (a
`README.md`, a `calc.py`), with the `qwen3-coder:30b` model and `bge-m3` on
the RunPod pod, the built interface (`npm run build`) served by the same
server. The scenario drives the API as the browser does: same routes, same
token, same SSE stream.

| Step | Result | Time |
| --- | --- | --- |
| `GET /api/config` without a token | `401` | — |
| `GET /` (built interface) | `200` | — |
| "What does the add function in calc.py do?" | `rag_sources` then the answer, which cites `calc.py` lines 1-2 | 11.8 s |
| The same question | **Served from the cache** (`cache_hit`), no model call | 1.4 s |
| "Create the file test_calc.py…" | The model first **asked for permission in text** instead of calling the tool (model behavior, not the server) | 23.5 s |
| "Yes, create it now…" | `tool_call` → `confirm_request` (creation diff) → "yes" (`204`) → file created | — |
| "Also create notes.txt…" then "no" | `tool_return` failed ("The user refused…"), file **not** created | — |
| `/state` | Command output, no model call | 0.0 s |
| Long explanation, interrupted after 0.5 s | `done` with `reason: "interrupted"`, nothing saved | 4.1 s |
| `GET /export?format=md` | `200`, `text/markdown` | — |
| `GET /api/sessions` | The session, with its title and 6 messages | — |

## Click-through trial in a browser

The same server, driven in Chrome (Chrome DevTools) like a user:

| Flow | Result |
| --- | --- |
| Open `http://127.0.0.1:8765/` | "Connect to CodeSensai" screen (server detected) |
| Wrong token | "Token rejected…", stays on the screen |
| Right token | Badge "Real agent · qwen3-coder:30b"; after reload, reconnects without asking again |
| "What does the add function in calc.py do?" | Live answer; Sources tab: `calc.py:1-2` (77%) |
| Write request | "Risky action · approval required" card with details; "Allow" → "✓ Allowed", observation "Created … (66 bytes)", file present on disk |
| Second request, "Deny" | "✕ Denied", the agent receives the refusal, file absent |
| Long explanation, "■ Stop" | "Generation interrupted", input becomes available again |
| "Edit message" | "Versions" bar: main branch and "Variant 1", a new session on the server side |
| Home page, connected | Pill "Connected to the real agent · qwen3-coder:30b" |
| Log page, after a `read_file` call | `read_file`, its arguments, 21 ms, "Success"; 1 call, 21 ms on average, 0% failures; "Tokens used" stays at 0 (simulated) |
| Export page | The Markdown preview contains the real conversation and the tool call; the share link is labeled as simulated |
| Browser console | No errors or warnings |

**Visible defects found by this trial, fixed and tested:**
- the model's code blocks (triple backticks) were shown as raw text;
- the chat welcome and the home page showed "simulated engine" or "simulated demo" even when connected;
- text written before and after a tool call was glued together ("…write_file.I created…");
- when the model writes its tool call as text (ADR-0031), the interface showed `<function=write_file>…`; it is now hidden, as in the CLI.

## Automated tests

- **Server** (`tests/web/`, 102 tests of the real server and the 15 of the
  prototype): token on every route, docs disabled, CORS closed, sessions
  shared with the CLI, stream with `done` last, model and core errors, one
  turn at a time, two sessions in parallel, confirmation (yes, no, timeout,
  late answer, double answer, values `"true"`/`1`/`"yes"` rejected),
  interruption, closed tab, blocked input, commands, cache, RAG sources,
  forking, export with secrets filtered, memories, served interface, tool
  parity with the CLI, purge at startup (#65). Run 5 times in a row: 117/117
  each time.
- **Interface** (`frontend/tests/`, 166 tests): stream translation
  (`wire.test.ts`), real engine against a fake server (`httpEngine.test.ts`),
  token login and demo mode (`connection.test.tsx`).

## Defect found while writing the tests, fixed

`approved` was a plain pydantic boolean: `"true"`, `1` or `"yes"` would have
been taken as "yes" and **allowed a write**. Only the JSON boolean `true` is
now accepted (`StrictBool`); anything else gets `400`.

## Limits

- **Reloading the page starts from an empty conversation** in the interface:
  the session stays saved on the server (and can be resumed in the CLI), but
  the interface does not reload it yet.
- A confirmation summary contains the file's **full path** (text produced by
  the `write_file` tool): it is visible in the browser, on the local machine.
- A single user, on the local machine; no load measurement.
