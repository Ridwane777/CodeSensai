# Web API (Lot D, web interface)

**For Lot D: the implementation contract of the web server, and the reference
for its HTTP API as it exists in `src/sensai/web/server.py`.**

Part I lists the Python APIs the server builds on. Part II lists every HTTP
route and every SSE event the server really sends. Part III explains how the
real server is put together. Last checked against the code on 2026-10-29
(after PRs #99 to #103).

---

## Part I: Core Python APIs

### 1. Reasoning loop: `run_agent_turn`

**Where:** `sensai.core.agent`

```python
def run_agent_turn(
    host: str,                      # "http://localhost:11434"
    model: str,                     # e.g. "qwen3:8b" (DEFAULT_MODEL in sensai.config)
    messages: list[dict],           # Conversation history
    tools: ToolCaller,              # The tool gateway (anything with describe_all() and call())
    num_ctx: int | None = None,     # Context window sent to Ollama (M2, ADR-0045)
) -> Iterator[Event]:
    """
    Runs one agent turn and yields events as they happen.

    - Calls the model through Ollama (streaming, native tool calling)
    - If it asks for tools, runs them through the gateway
    - Loops until a final answer or MAX_ITERATIONS
    - Yields Token, Thought, ToolCall, ToolReturn, Error, Done

    `messages` is not modified: the turn's internal exchanges stay in a copy.
    The caller decides what it keeps in the history.
    """
```

**Usage example:**

```python
from sensai.core.agent import run_agent_turn
from sensai.core.tools import ToolRegistry
from sensai.execution.gateway import ToolGateway

registry = ToolRegistry()
# ... register the tools ...
gateway = ToolGateway(registry, confirm=my_confirmer)

messages = [
    {"role": "system", "content": "Tu es CodeSensei."},
    {"role": "user", "content": "Aide-moi à déboguer ce code."},
]

for event in run_agent_turn("http://localhost:11434", "qwen3:8b", messages, gateway):
    print(event)
    # send to_wire(event) to the browser
```

The real web server does not call `run_agent_turn` directly: it goes through
`WebRuntime.run_turn` (`sensai.web.runtime`), which adds the answer cache,
RAG, the token budget and the guardrails, then calls `run_agent_turn`
(see Part III).

---

### 2. Plain text streaming: `stream_chat` and `stream_chat_messages`

**Where:** `sensai.core.ollama_client`

```python
def stream_chat(
    host: str,
    model: str,
    messages: list[dict],
    num_ctx: int | None = None,
) -> Iterator[str]:
    """Streams only the answer text, no tool handling. Each chunk is a str."""

def stream_chat_messages(
    host: str,
    model: str,
    messages: list[dict],
    tools: list[dict[str, Any]] | None = None,
    format: dict[str, Any] | str | None = None,
    options: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    """
    Streams Ollama's raw `message` objects: `content`, `thinking` and
    `tool_calls` depending on what the model produces.

    Used internally by run_agent_turn. Call it directly only when you do not
    want a ReAct loop.
    """
```

Both raise `OllamaError` when Ollama cannot be reached or answers with an error.

---

### 3. Running tools: `ToolRegistry` and `ToolGateway`

**Where:** `sensai.core.tools` and `sensai.execution.gateway`

#### ToolRegistry (no permissions)

```python
from sensai.core.tools import ToolRegistry

registry = ToolRegistry()
registry.register(my_tool)           # Register a tool
tool = registry.get("tool_name")     # Get a tool (or None)
tools_list = registry.describe_all() # Describe every tool

# WARNING: runs WITHOUT permissions, guardrails or confirmation
result = registry.call("tool_name", param1="value1")
```

#### ToolGateway (with safety)

```python
from sensai.execution.gateway import ToolGateway
from sensai.execution.guardrails import filter_output
from sensai.execution.tool_policy import ToolPreferences

prefs = ToolPreferences(
    disabled=frozenset({"dangerous_tool"}), # Disabled tools
    modes={"write_file": "ask"},            # Ask for confirmation before writing
    tool_timeout_s=120.0,                   # Max duration of a tool call (default 120)
    confirm_timeout_s=60.0,                 # Time to answer yes/no (default 60)
    max_output_chars=20_000,                # Max size returned to the model (default 20,000)
)

gateway = ToolGateway(
    registry,
    preferences=prefs,
    confirm=my_confirmer,          # Called before a risky action (default: deny_all)
    input_guards=[my_guard],       # Input guardrails (EV2), return a Decision
    output_filters=[filter_output] # Output filters (EV2), e.g. secret masking
)

result = gateway.call("tool_name", param1="value1")  # with ALL protections
visible_tools = gateway.describe_all()               # what the model may see
```

`ToolPreferences` is defined in `sensai.execution.tool_policy` (the gateway
module imports it from there).

**Result:** `ToolResult`

```python
@dataclass
class ToolResult:
    ok: bool                                            # Success?
    content: str                                        # Text for the model
    data: dict[str, Any] = field(default_factory=dict)  # Structured data
```

On failure the gateway puts a stable code in `data["error"]`: `unknown_tool`,
`disabled`, `invalid_arguments`, `denied_by_policy`, `blocked`, `refused`,
`invalid_result`, `filter_failed`, `timeout`, `network_error`, `tool_error`.

---

### 4. Events: `sensai.core.events`

Everything `run_agent_turn` yields. Serialisable to JSON with `to_wire`.

```python
from sensai.core.events import (
    Token, Thought, ToolCall, ToolReturn, Error, Done,
    Event, to_wire,
)

Token(text="La réponse ")                              # piece of the final answer
Thought(text="Je dois chercher le fichier de config")  # reasoning before acting
ToolCall(id="tool_1", name="search_codebase", arguments={"query": "config.yaml"})
ToolReturn(id="tool_1", name="search_codebase", ok=True, content="Trouvé 3 fichiers...")
Error(message="Ollama injoignable")                    # the turn is lost
Done(reason="final_answer")                            # always last; or "error", "max_iterations"

to_wire(Token(text="..."))  # -> {"type": "token", "text": "..."}
```

A failing tool is not an `Error`: it is a `ToolReturn(ok=False)` and the agent
goes on.

---

### 5. Confirmation: `ConfirmationRequest` and `Confirmer`

**Where:** `sensai.execution.gateway`

The gateway calls your `confirm` function when a risky action needs
permission.

```python
@dataclass(frozen=True)
class ConfirmationRequest:
    tool: str            # Tool name, e.g. "execute_code"
    risk: Risk           # read, write, execute, network
    summary: str         # Readable plan: the tool's describe_call(), else name(args)
    arguments: dict[str, Any]
    timeout_s: float     # Delay before an automatic refusal

# A Confirmer is a SYNCHRONOUS function: it blocks until the answer and
# returns True (approve) or False (refuse).
Confirmer = Callable[[ConfirmationRequest], bool]
```

Contract rules: no answer in time = `False`, browser disconnected = `False`,
crashed confirmer = `False` (never an exception). Only a literal `True`
authorises. For `write_file`, `summary` contains the exact path and, when a
file is replaced, a unified diff (the web interface colours it).

**Do not rewrite this confirmer by hand: use `WebConfirmationBroker`**
(`sensai.execution.web_confirmation`, [ADR-0015](../../decisions/0015-confirmation-web-synchrone.md)).
It is thread-safe, does not depend on a web framework, and already applies
these rules:

```python
from sensai.execution.web_confirmation import WebConfirmationBroker

broker = WebConfirmationBroker(emit)       # emit(payload: dict) -> None
gateway = ToolGateway(registry, confirm=broker.confirmer)

broker.resolve(confirm_id, approved)       # -> bool, called by POST /confirm
broker.pending_ids()                       # requests still unanswered
broker.close()                             # refuses everything; call it on disconnect
```

- `emit` receives the `confirm_request` event (`type`, `id`, `tool`, `risk`,
  `summary`, `arguments`, `timeout_s`). It is called from the agent's
  thread: it must be thread-safe. The server adds `confirm_id` (same value
  as `id`) before sending it.
- `resolve` returns `True` only if a pending request had that id; otherwise
  `False` (unknown, already answered, expired), without an exception. The
  first answer wins. **Only JSON `true` authorises**: `false`, `1`, `"true"`,
  `null` or a missing field mean refusal.
- The broker waits at most `timeout_s` itself: after that the request
  disappears and a late answer returns `False`.
- After `close()`, any new request is refused at once, without `emit`.
- The confirmer **blocks the thread that calls it**: the agent turn must run
  in a worker thread, never in the event loop.

Questions to the user (`ask_user`, X4, [ADR-0046](../../decisions/0046-ask-user-tool.md))
follow the same pattern with `WebQuestionBroker` (`sensai.web.questions`):
`ask(question)` emits a `question` event and waits at most 100 s
(`ANSWER_TIMEOUT_S`); `resolve(question_id, values)` returns `"ok"`,
`"unknown"` or an error message; `close()` leaves pending questions
unanswered.

---

### 6. History: `History`

**Where:** `sensai.core.history`

```python
from sensai.core.history import History

history = History(
    system_prompt="Tu es CodeSensei, expert en Python.",
    turns=[],  # previous turns, when resuming a session
)

history.add_user("Aide-moi avec ce bug")
history.add_assistant("Je vais analyser...")
messages = history.as_messages()  # system prompt first, then the turns
history.drop_last()               # remove the last turn (failed call)
```

The web server does not use `History`: it loads and saves the turns with
`SessionStore` (`sensai.knowledge.memory`, SQLite).

---

### 7. Configuration: `get_settings`

**Where:** `sensai.config`

```python
from sensai.config import get_settings

settings = get_settings()  # command-line arguments + config.json (DEFAULT_CONFIG_PATH)

settings["host"]              # "http://localhost:11434" by default
settings["model"]             # "qwen3:8b" by default
settings["system_prompt"]     # system prompt text
settings["session"]           # session id to resume (or None)
settings["new_session"]       # force a new session?
settings["data_dir"]          # where sessions and profiles are stored
settings["memory_prompt"]     # resume instruction (M1)
settings["retention_days"]    # session retention, 30 by default (M1)
settings["rag"]               # RAG on? (R1)
settings["rag_model"]         # embedding model, "bge-m3" by default (R1)
settings["rag_min_score"]     # min relevance score, 0.54 by default (R1)
settings["rag_top_k"]         # top K passages, 5 by default (R1)
settings["rag_rerank"]        # reranking on? (R1)
settings["num_ctx"]           # context window (M2)
```

Other keys exist (`tool_preferences`, `mcp_servers`, `personas`, `cache`,
`token_budget`…): see `get_settings` in `src/sensai/config.py`.

---

## Part II: HTTP API (web server routes)

The server is `create_app(runtime, *, token, allowed_origins=(), frontend_dir=None)`
in `sensai.web.server`, started by the `sensai-web` command
(`sensai.web.cli`). Decisions: [ADR-0022](../../decisions/0022-transport-sse-et-modele-d-execution.md)
(one turn = one SSE stream), [ADR-0023](../../decisions/0023-acces-a-l-api-web.md)
(token, local listening, closed CORS), [ADR-0024](../../decisions/0024-extensions-du-contrat-web.md)
(contract extensions), [ADR-0035](../../decisions/0035-serveur-web-reel.md)
(real server).

### Authentication and transport

- `sensai-web` listens on `127.0.0.1:8000` by default (`--bind`, `--port`).
- At start it prints a random access token (`secrets.token_urlsafe(32)`),
  shown once, never written to a file or a URL.
- Every route marked **token** requires `Authorization: Bearer <token>`.
  Missing, wrong or malformed token: **401** `UNAUTHORIZED` (same answer in
  all three cases, compared in constant time).
- Only `GET /api/health` and `GET /share/{token}` work without the token.
- CORS is off unless `--allow-origin` is given (closed list, never `*`;
  methods `GET`, `POST`).
- No OpenAPI or Swagger page (`docs_url=None`).
- If the built interface exists (`frontend/dist/index.html`), it is served
  at `/`.

### Error format

Every API error has this body:

```json
{"error": "Session introuvable", "code": "SESSION_NOT_FOUND", "details": "La session abc123 n'existe pas ou a été purgée"}
```

Common codes:

| Status | Code | When |
|---|---|---|
| 400 | `INVALID_REQUEST` | Body or parameters fail validation (wrong type, missing field) |
| 401 | `UNAUTHORIZED` | Token missing, wrong or malformed |
| 404 | `SESSION_NOT_FOUND` | Unknown or purged `session_id` (every `/api/sessions/{id}/…` route) |

Route-specific codes are listed with each route.

### Route summary

| # | Method | Path | Auth | Success |
|---|---|---|---|---|
| 1 | GET | `/api/health` | none | 200 |
| 2 | GET | `/api/config` | token | 200 |
| 3 | POST | `/api/sessions` | token | 201 |
| 4 | GET | `/api/sessions` | token | 200 |
| 5 | GET | `/api/sessions/{session_id}` | token | 200 |
| 6 | POST | `/api/sessions/{session_id}/fork` | token | 201 |
| 7 | POST | `/api/sessions/{session_id}/delete` | token | 204 |
| 8 | GET | `/api/sessions/{session_id}/export` | token | 200 |
| 9 | POST | `/api/sessions/{session_id}/share` | token | 201 |
| 10 | POST | `/api/shares/{token}/revoke` | token | 204 |
| 11 | GET | `/share/{token}` | none | 200 (HTML) |
| 12 | POST | `/api/sessions/{session_id}/messages` | token | 200 (SSE) |
| 13 | POST | `/api/sessions/{session_id}/confirm` | token | 204 |
| 14 | POST | `/api/sessions/{session_id}/answer` | token | 204 |
| 15 | POST | `/api/sessions/{session_id}/interrupt` | token | 204 |
| 16 | GET | `/api/profile` | token | 200 |
| 17 | GET | `/api/facts` | token | 200 |
| 18 | GET | `/api/state` | token | 200 |
| 19 | POST | `/api/profile/preferences` | token | 200 |
| 20 | POST | `/api/profile/forget` | token | 200 |
| 21 | POST | `/api/sessions/{session_id}/evaluate` | token | 200 |
| 22 | GET | `/api/schedule/tasks` | token | 200 |
| 23 | POST | `/api/schedule/tasks` | token | 201 |
| 24 | POST | `/api/schedule/tasks/{task_id}/remove` | token | 204 |
| 25 | POST | `/api/schedule/tasks/{task_id}/enabled` | token | 204 |
| 26 | GET | `/api/quality/adversarial` | token | 200 |
| 27 | POST | `/api/quality/adversarial/run` | token | 200 |
| 28 | GET | `/api/journal?session=&limit=` | token | 200 |
| 29 | GET | `/api/journal/metrics?days=` | token | 200 |
| 30 | GET | `/api/personas` | token | 200 |
| 31 | GET | `/api/sessions/{session_id}/persona` | token | 200 |
| 32 | POST | `/api/sessions/{session_id}/persona` | token | 200 |
| 33 | GET | `/api/prompts` | token | 200 |
| 34 | GET | `/api/prompts/{name}/{version}` | token | 200 |
| 35 | GET | `/api/prompts/{name}/diff?a=&b=` | token | 200 |
| 36 | GET | `/api/sessions/{session_id}/prompt-trial` | token | 200 |
| 37 | POST | `/api/sessions/{session_id}/prompt-trial` | token | 200 |
| 38 | GET | `/api/fewshot` | token | 200 |

Routes 21 to 25 and the `usage`, `compression`, `artifact_patch`,
`subagent_step` and `fewshot` events were added on 2026-10-29 on branch
`lot-d/web-real-features` ([ADR-0050](../../decisions/0050-real-web-features-on-demand-evaluation.md),
Proposed). Tested with pytest (scripted model) and vitest, not with the real
model.

Routes 26 to 29 were added on 2026-11-01 (EV4 corpus, Lot B; EV3 journal,
Lot D, [ADR-0053](../../decisions/0053-server-side-turn-journal.md), Proposed),
and `subagent_step` gained `duration_ms`. Checked with `qwen3-coder:30b`, in the
API and the browser (2026-11-01). Routes 30 to 37 (A5 personas and A4 prompt
versions, Lot A, [ADR-0054](../../decisions/0054-personas-in-the-web.md) and
[ADR-0055](../../decisions/0055-prompt-versions-in-the-web.md), Proposed) were added
the same day and checked with the real model.

---

### Health and configuration

#### 1. `GET /api/health` (no token)

```json
{"status": "ok"}
```

Deliberately without details.

#### 2. `GET /api/config`

```json
{
  "model": "qwen3-coder:30b",
  "project": "my-project",
  "rag": true,
  "rerank": true,
  "cache": true,
  "notices": ["Recherche dans le projet désactivée : ..."]
}
```

`project` is the folder name only. Never the Ollama address, the token or a
full path (ADR-0023). `notices` lists features turned off at runtime.

---

### Sessions

#### 3. `POST /api/sessions` → 201

No body. Creates an empty session in the current project.

```json
{"session_id": "abc123def456"}
```

#### 4. `GET /api/sessions` → 200

Sessions of the current project that have at least one message, most recent
first. Returns a JSON **array** (not an object):

```json
[
  {"session_id": "abc123def456", "title": "...", "created_at": "...",
   "updated_at": "...", "message_count": 12}
]
```

#### 5. `GET /api/sessions/{session_id}` → 200

```json
{"session_id": "abc123def456",
 "messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

`messages` are the stored turns as saved by the runtime (no timestamp per
message). Errors: 404 `SESSION_NOT_FOUND`.

#### 6. `POST /api/sessions/{session_id}/fork` → 201

Fork (X2, ADR-0024): a new session holding the first `at_message` messages
of this one.

```json
{"at_message": 4}
```

Response: `{"session_id": "<new id>"}`. Errors: 400 `INVALID_REQUEST` if
`at_message` is negative or greater than the number of messages; 404
`SESSION_NOT_FOUND`.

#### 7. `POST /api/sessions/{session_id}/delete` → 204

Deletes the conversation and its messages (chat sidebar), and its rows in the
turn journal (EV3, since 2026-11-01). No body. Errors:
409 `TURN_IN_PROGRESS` while a turn runs on this session; 404
`SESSION_NOT_FOUND`. Limit: `SessionStore.delete` does not run `VACUUM`, so
the deleted text stays in the SQLite file's free pages until the next
`VACUUM` (the retention purge runs one). Fixed on 2026-10-29: `delete` now
runs `VACUUM` (`_vacuum()`, shared with `purge`); checked by
`tests/knowledge/test_memory.py::test_supprimer_une_session_efface_aussi_son_texte_du_fichier`.

#### 8. `GET /api/sessions/{session_id}/export?format=json|md` → 200

Export with secrets masked by `filter_output` (X3, ADR-0024). `format`
defaults to `json`; any other value gives 400 `INVALID_REQUEST`.

- `json`: `{"session_id", "messages": [{"role", "content"}]}`, header
  `Content-Disposition: attachment; filename="codesensei-<id>.json"`.
- `md`: `text/markdown`, one `## Vous` / `## CodeSensei` section per
  message, file `codesensei-<id>.md`.

PDF export is done in the browser. Errors: 404 `SESSION_NOT_FOUND`.

---

### Share links (X3, [ADR-0048](../../decisions/0048-share-links.md))

#### 9. `POST /api/sessions/{session_id}/share` → 201

No body. Takes a snapshot of the user and assistant messages, passed through
`filter_output`, stored in `<data_dir>/shares.json` (file mode 600) under the
SHA-256 of a `secrets.token_urlsafe(32)` token. Expires after 7 days.

```json
{"url": "/share/<token>", "token": "<token>", "expires_at": "2026-11-05T10:30:00+00:00"}
```

Errors: 400 `EMPTY_SESSION` (no message yet); 404 `SESSION_NOT_FOUND`.

#### 10. `POST /api/shares/{token}/revoke` → 204

No body. Errors: 404 `SHARE_NOT_FOUND`. The Export page calls it from the
"Révoquer le lien" button (since 2026-10-31). Expired links are purged when
the server starts.

#### 11. `GET /share/{token}` (no API token) → 200 HTML

Static read-only page of the shared conversation, all text HTML-escaped.
Headers: `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`
(no script), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`X-Robots-Tag: noindex, nofollow`, `Cache-Control: no-store`. Unknown,
revoked or expired link: the same **404** HTML page "Lien indisponible",
without saying which case. Reachable only by whoever can reach `sensai-web`
(127.0.0.1 by default).

---

### A turn

#### 12. `POST /api/sessions/{session_id}/messages` → 200 SSE

```json
{"content": "Pourquoi ce test échoue ?", "skip_cache": false}
```

`skip_cache` (strict boolean, default `false`) asks the model again without
the answer cache (A6); the interface sets it for `/again` and "↻ Régénérer".

Response: `Content-Type: text/event-stream`, headers `Cache-Control: no-cache`
and `X-Accel-Buffering: no`. Each event is a line `data: <JSON>` followed by
an empty line; the stream closes after `done`.

Errors (before the stream opens): 400 `EMPTY_MESSAGE` (empty after trimming);
413 `MESSAGE_TOO_LONG` (more than 20,000 characters, `MAX_MESSAGE_CHARS`);
409 `TURN_IN_PROGRESS` (one turn at a time per session; several sessions can
run in parallel); 404 `SESSION_NOT_FOUND`.

Closing the stream (tab closed) cancels the turn: pending confirmations
become refusals and pending questions stay unanswered.

**Example stream:**

```
data: {"type":"rag_sources","sources":[{"path":"tests/test_login.py","lines":"1-40","score":0.71}]}

data: {"type":"thought","text":"Je dois comprendre le test"}

data: {"type":"tool_call","id":"tool_1","name":"execute_code","arguments":{"code":"..."}}

data: {"type":"confirm_request","id":"c1","confirm_id":"c1","tool":"execute_code","risk":"execute","summary":"...","arguments":{"code":"..."},"timeout_s":60.0}

data: {"type":"tool_return","id":"tool_1","name":"execute_code","ok":true,"content":"FAILED test_login.py::test_admin_login"}

data: {"type":"token","text":"Le test échoue car la fixture n'est pas appliquée."}

data: {"type":"done","reason":"final_answer"}
```

**SSE events:**

| Type | Fields | Source |
|---|---|---|
| `token` | `text` | Answer text (`Token`), also the cached answer and slash-command output |
| `thought` | `text` | Model reasoning (`Thought`) |
| `tool_call` | `id`, `name`, `arguments` | `ToolCall` |
| `tool_return` | `id`, `name`, `ok`, `content` | `ToolReturn` |
| `error` | `message` | `Error`, or "Erreur interne du serveur." if the turn crashes |
| `done` | `reason` | Always last. `final_answer`, `max_iterations`, `error`, `interrupted`, `blocked` (input guardrail), `command` (slash command) |
| `confirm_request` | `id`, `confirm_id` (same value), `tool`, `risk`, `summary`, `arguments`, `timeout_s` | `WebConfirmationBroker` |
| `question` | `question_id`, `title`, `fields`, `timeout_s` | `WebQuestionBroker` (`ask_user`, X4, ADR-0046); `timeout_s` is 100 |
| `agent_handoff` | `from`, `to` | Relay between agents (X1/A2, [ADR-0047](../../decisions/0047-real-agent-handoffs-in-the-web.md)); `"main"` is the main agent |
| `rag_sources` | `sources`: list of `{path, lines, score}` | Passages found in the project (R1) |
| `cache_hit` | `similarity`, `question`, `created_at` | Answer served from the cache (A6), followed by `token` and `done` |
| `guardrail` | `kind` (`"unsafe"`), `message` | Message blocked by an input guardrail (EV2), followed by `done` (`blocked`) |
| `usage` | `used`, `budget`, `num_ctx`, `estimated` (always `true`) | Every turn, before the answer: **estimated** tokens (characters / 4) of what is sent to the model (M2); the interface shows the token bar and the context % (`used / num_ctx`) |
| `compression` | `saved_tokens` | The sliding summary ran this turn (M2) |
| `artifact_patch` | `section`, `markdown` | One per section of the state document (`SENSAI.md`, M4) changed by an `update_state` call; fills the Artefact panel |
| `subagent_step` | `agent`, `tool`, `arguments`, `ok`, `content`, `duration_ms` | One per tool run by a sub-agent (`delegate_task` and every `team_task` role, A2); `content` already filtered by the gateway and cut at 600 characters; shown as "agent › tool" |
| `fewshot` | `question` | A few-shot example (A7) was attached to the question (`fewshot_examples`, `fewshot_min_score`); `question` cut at 200 characters |

`agent_handoff` is sent when a `delegate_task` sub-agent actually starts
(`to` = its role or `"sous-agent"`), at each `team_task` relay (explorateur →
developpeur → relecteur, including send-backs), and back to `"main"` just
before the tool's `tool_return`. A delegation refused at confirmation sends
no relay. Since 2026-10-29 the sub-agents' own tool runs are streamed as
`subagent_step` events.

#### 13. `POST /api/sessions/{session_id}/confirm` → 204

```json
{"confirm_id": "c1", "approved": true}
```

`approved` is a strict boolean: only JSON `true` authorises; `"true"`, `1`
or `"yes"` give 400 `INVALID_REQUEST`. The SSE stream keeps going either
way: with `false` (or after the delay), the gateway returns a failed
`tool_return` to the agent, which adapts its answer, and the turn ends with
`done`.

Errors: 404 `CONFIRM_NOT_FOUND` (unknown, already answered or expired id, or
no turn running); 404 `SESSION_NOT_FOUND`.

#### 14. `POST /api/sessions/{session_id}/answer` → 204

Answer to a `question` event (X4, ADR-0046).

```json
{"question_id": "question_3f2a...", "values": {"name": "value"}}
```

`values` are checked against the form fields. Errors: 400 `INVALID_ANSWER`
(invalid values; `details` says why; the question stays open); 404
`QUESTION_NOT_FOUND` (unknown or expired, or no turn running); 404
`SESSION_NOT_FOUND`. Without an answer (timeout, interrupt, tab closed) the
tool fails and tells the model not to guess. Answers go back as a tool
result, so the gateway's output filters (EV2) mask secrets.

#### 15. `POST /api/sessions/{session_id}/interrupt` → 204

No body. If a turn is running: sets its cancel flag, refuses the pending
confirmation and closes the pending question. With no turn running it does
nothing and still answers 204. Errors: 404 `SESSION_NOT_FOUND`.

---

### Memories

#### 16. `GET /api/profile` → 200

```json
{"name": "...", "instructions": "...", "preferences": ["..."]}
```

#### 17. `GET /api/facts` → 200

`{"facts": {"<entity>": [...]}}` for up to 200 entities. Errors: 500
`FACTS_UNAVAILABLE` if the fact memory cannot be read.

#### 18. `GET /api/state` → 200

```json
{"markdown": "...", "sections": [...], "bodies": {"<section>": "..."}}
```

The project state document (empty string if none). `bodies` (added on
2026-10-29) maps each section name to its content; the interface fills the
Artefact panel with it at load.

#### 19. `POST /api/profile/preferences` → 200

Body `{"text": "..."}` (500 characters at most). Adds a preference, like
`/remember` in the CLI; empty or already present: ignored. Returns the profile
(same shape as route 16). Errors: 400 `TOO_MANY_PREFERENCES` above 50
preferences; 400 `INVALID_REQUEST` if the text is longer than 500 characters.

#### 20. `POST /api/profile/forget` → 200

No body. Clears all preferences, like `/forget` in the CLI, and returns the
profile. It is a `POST` and not the `DELETE /api/profile` planned in US-WEB-6,
because the server only allows `GET` and `POST` (CORS).

### Evaluation (EV1)

#### 21. `POST /api/sessions/{session_id}/evaluate` → 200

No body. Judges the **last answer** of the conversation with the
`sensai-eval` judge. It costs one more model call, so it runs **on demand
only** (the Quality page button "Évaluer la dernière réponse"), never at
every turn: that would roughly double the answer time.

```json
{"scores": {"relevance": 4, "coherence": 5, "faithfulness": 0.8},
 "passages": 3, "question": "...", "flagged": [{"text": "...", "verdict": "..."}]}
```

`relevance` and `coherence` are 1-5; `faithfulness` is 0-1, or `null` when no
project passage was found (RAG off or nothing relevant). `passages` is the
number of passages given to the judge; `flagged` lists the claims the judge
did not find supported (text filtered for secrets). Errors: 400
`NOTHING_TO_EVALUATE` (no answer yet); 502 `EVALUATION_FAILED` (the judge
failed or returned no usable score); 404 `SESSION_NOT_FOUND`.

### Scheduled tasks (X5)

These routes read and write `<data_dir>/schedule/tasks.json`, the same file
as `sensai-schedule`. **The web server never runs a task**: `sensai-schedule
loop` (or `run-due`) does.

#### 22. `GET /api/schedule/tasks` → 200

List of tasks: the fields of `sensai-schedule`'s `Task` plus `next_due` (ISO
date or `null`). Error: 500 `TASKS_UNREADABLE`.

#### 23. `POST /api/schedule/tasks` → 201

Body `{"id": "daily-summary", "prompt": "...", "every": "1d"}` (`every` in
the `sensai-schedule` format: `30m`, `2h`, `1d`). Like `sensai-schedule
add`. Returns the task. Errors: 400 `INVALID_TASK` (bad id, bad interval,
empty prompt, id already used); 500 `TASKS_UNREADABLE`.

#### 24. `POST /api/schedule/tasks/{task_id}/remove` → 204

Error: 404 `TASK_NOT_FOUND`.

#### 25. `POST /api/schedule/tasks/{task_id}/enabled` → 204

Body `{"enabled": false}` (strict boolean): pauses or resumes the task.
Error: 404 `TASK_NOT_FOUND`.

### Adversarial corpus (EV4, Lot B)

The corpus is `src/sensai/eval/adversarial.py`, the same one as
`tests/adversarial/` and `scripts/adversarial_run.py`. It **never calls the
model**; Docker is replaced by fakes (`sensai/eval/docker_fakes.py`), so no
container is started.

#### 26. `GET /api/quality/adversarial` → 200

The last run made by this server, or, if none, the committed table
(`docs/performance/data/EV4-adversarial-results.md`, parsed; `detail` empty).

```json
{"cases": [{"id": "EV4-INJ-01", "category": "INJ", "attempt": "...",
            "expected": "SIGNALÉ", "observed": "SIGNALÉ", "verdict": "OK", "detail": "..."}],
 "summary": {"total": 85, "ok": 65, "known_gaps": 20, "regressions": 0, "fixed": 0, "skipped": 0},
 "ran_at": "2026-11-01T10:00:00+00:00", "source": "run"}
```

`ran_at` is `null` and `source` is `"committed"` for the committed table
(`"none"` with an empty list if the file is absent, e.g. an installed package).
Labels and verdicts are the French ones of the generated table.

#### 27. `POST /api/quality/adversarial/run` → 200

No body. Reruns the 85 cases (about 0.6 s on the dev machine, measured once on
2026-11-01) in a worker thread and returns the same shape with `source: "run"`.
Errors: 409 `ALREADY_RUNNING` while a run is in progress; 500
`ADVERSARIAL_FAILED` if the runner crashes. Cases that cannot run here (no
symlink support, browser Dockerfile missing) are reported with the verdict
`IGNORÉ`, like the script.

### Turn journal (EV3, Lot D)

Stored in `<data_dir>/journal.db` by the web server and the CLI
([ADR-0053](../../decisions/0053-server-side-turn-journal.md)). Errors for both
routes: 503 `JOURNAL_UNAVAILABLE` if the file could not be opened at start; 500
`JOURNAL_UNREADABLE`.

#### 28. `GET /api/journal?session=<id>&limit=50` → 200

The turns of one conversation, newest first (`limit` 1-500), each with its tool
calls in order:

```json
{"session_id": "598e74dbd321",
 "turns": [{"id": 7, "session_id": "598e74dbd321", "started_at": "2026-11-01T10:00:00+00:00",
            "model_ms": 1840, "tokens_sent": 2310, "outcome": "final_answer", "interface": "web",
            "tools": [{"tool": "read_file", "arguments": "{\"path\": \"notes.md\"}",
                       "duration_ms": 12, "ok": true, "agent": "main"}]}]}
```

`arguments` is a JSON string filtered by the EV2 output filter and cut at 500
characters. `agent` is `"main"` or the sub-agent role. `outcome` is the `done`
reason (`final_answer`, `error`, `max_iterations`) or `interrupted`.
`tokens_sent` is estimated (characters / 4). An unknown session returns an
empty list.

#### 29. `GET /api/journal/metrics?days=7` → 200

```json
{"days": 7,
 "tools": [{"tool": "read_file", "calls": 12, "failures": 1, "mean_ms": 18, "max_ms": 95}],
 "model": {"turns": 9, "mean_ms": 2100, "max_ms": 6400, "not_final": 1}}
```

Over the turns started in the last `days` days (1-3650), all conversations and
both interfaces. Durations are wall-clock: a tool's includes the user's
confirmation time.
### Personas (A5, Lot A — [ADR-0054](../../decisions/0054-personas-in-the-web.md))

Added on 2026-11-01. The persona is chosen **per conversation** and held in
server memory (not saved in `sessions.db`, not restored after a restart). A
conversation without a choice uses the config's default persona. Persona
creation and keyword routing were removed (ADR-0056).

#### 30. `GET /api/personas` → 200

`[{"id", "name", "role", "tone", "scope", "tools_disabled": [...], "default": bool}]`,
sorted by id.

#### 31. `GET /api/sessions/{session_id}/persona` → 200

The conversation's persona, same shape as one item of route 30. Error: 404
`SESSION_NOT_FOUND`.

#### 32. `POST /api/sessions/{session_id}/persona` → 200

Body `{"persona": "relecteur"}`. Returns the persona. From the next turn: its
block is in the system prompt, its `tools_disabled` are added to the tools
already disabled by `config.json` (main agent and sub-agents), and the answer
cache is skipped if it disables tools. Errors: 404 `SESSION_NOT_FOUND`, 404
`PERSONA_NOT_FOUND`, 409 `TURN_IN_PROGRESS`.

### Prompt versions (A4, Lot A — [ADR-0055](../../decisions/0055-prompt-versions-in-the-web.md))

Added on 2026-11-01. **Read-only on the registry** (`prompts/versions.json`):
the web server never saves a version nor moves the active bookmark; that
stays `sensai-prompt use`.

#### 33. `GET /api/prompts` → 200

`[{"name": "system", "active": "v3", "versions": [{"id", "date", "author", "description", "active"}]}]`,
versions from the most recent.

#### 34. `GET /api/prompts/{name}/{version}` → 200

`{"name", "version", "text"}`; `version` accepts `v2` or `2`. Errors: 404
`PROMPT_NOT_FOUND`, 404 `PROMPT_VERSION_NOT_FOUND`.

#### 35. `GET /api/prompts/{name}/diff?a=v2&b=v3` → 200

`{"name", "a", "b", "diff"}`, `diff` being a unified diff. Same 404 errors.

#### 36. `GET /api/sessions/{session_id}/prompt-trial` → 200

`{"prompt": "system", "active": "v3", "trial": "v2" | null}`.

#### 37. `POST /api/sessions/{session_id}/prompt-trial` → 200

Body `{"version": "v2"}` or `{"version": null}`. The next turns of that
conversation (and its sub-agents) use that system version instead of the
system prompt loaded at startup; `null` goes back. In server memory only; a
turn under trial skips the answer cache. Errors: 404 `SESSION_NOT_FOUND`, 404
`PROMPT_VERSION_NOT_FOUND`, 409 `TURN_IN_PROGRESS`.

#### 38. `GET /api/fewshot` → 200

`{"configured": bool, "file": str | null, "min_score": float, "questions": [str], "error": str | null}`:
the few-shot examples (A7) the server loaded, read-only. A missing or broken
file gives `questions: []` and the reason in `error`, never an HTTP error.

---

## Part III: How the server is built

The previous version of this section was a FastAPI skeleton written before
the server existed. The real implementation is `src/sensai/web/server.py`;
this is what it does:

- **No session in memory.** The history is read from and written to
  `SessionStore` (SQLite) at each turn. The server only keeps a `Live`
  object per session during a turn: a lock, a `busy` flag (409 for a second
  turn), a cancel `threading.Event`, the `WebConfirmationBroker` and the
  `WebQuestionBroker` of that turn.
- **Agent in a worker thread.** `send_message` starts a thread that calls
  `WebRuntime.run_turn(turns, content, emit, cancel, broker.confirmer,
  skip_cache=..., asker=questions.ask)` and saves the new turns if it
  returns any. Events cross to the asyncio loop with
  `loop.call_soon_threadsafe(queue.put_nowait, item)`; `None` ends the
  stream.
- **`WebRuntime`** (`sensai.web.runtime`) is the same agent as the CLI
  (ADR-0035): input guardrail, slash commands, answer cache, RAG, token
  budget, then `run_agent_turn`, with `to_wire` on each event. It registers
  `ask_user` and announces relays with `agent_handoff`.
- **Cleanup.** When the stream ends normally or the browser disconnects,
  the `finally` blocks set `cancel`, close both brokers and clear `busy`. A
  crashing turn sends `error` then `done` (`reason: "error"`), so the stream
  never hangs.
- **Errors** are `ApiError(status, code, error, details)` turned into the
  JSON format above; pydantic validation errors become 400
  `INVALID_REQUEST`.

---

## Part IV: Checklist for Lot D

- [x] HTTP routes implemented (37 routes, Part II; 18, then 20, then 25, until 2026-11-01)
- [x] SSE opened and closed correctly (closed after `done`, cancel on disconnect)
- [x] Authentication (bearer token, ADR-0023)
- [x] Confirmation timeouts (`WebConfirmationBroker`; the interface shows the `timeout_s` countdown and handles the late 404)
- [x] Python events serialised to JSON (`to_wire` plus web-only events)
- [x] History saved and loaded (SQLite, `SessionStore`)
- [x] Error handling (Ollama unreachable → `error` + `done`)
- [x] Integration tests with Lot A (pytest with a scripted model; not run against the real model)

---

## References

- `sensai.web.server.create_app`: source of truth for the routes
- `sensai.web.runtime.WebRuntime`: one web turn
- `sensai.core.agent.run_agent_turn`: source of truth for the loop
- `sensai.core.events`: the core events
- `sensai.execution.gateway.ToolGateway`: secure gateway
- `sensai.execution.web_confirmation.WebConfirmationBroker`: confirmation from the browser ([ADR-0015](../../decisions/0015-confirmation-web-synchrone.md))
- `sensai.web.questions.WebQuestionBroker`: questions from the agent ([ADR-0046](../../decisions/0046-ask-user-tool.md))
- `docs/architecture/web/api-contract.md`: high-level contract (this doc refines it)
- `docs/architecture/tool-contract.md`: how to declare a tool
