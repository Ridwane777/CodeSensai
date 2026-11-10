# Technical requirements — Web server (HTTP facade over the core)

> Moved from `docs/user-stories/` on 2026-11-02: these are technical requirements shared by the features, not user stories of one catalogue feature.

Workstream D — Interface & wiring (Christopher). These stories describe how the **web server**
should behave, seen from the browser, **before** aligning the ADRs. They complete
[README.md](../user-stories/README.md), which describes the interface itself.

Sources: Workstream A's contract ([api-contract.md](../architecture/web/api-contract.md), [web-api.md](../architecture/web/web-api.md)), the code
merged into `main` (`sensai.core`, `sensai.execution`, `sensai.knowledge`) and
[ADR-0005](../decisions/0005-web-interface-facade.md).

Confirmation on the core side (the broker that waits for the browser's answer) has its own stories, written by
Workstream B: [A3-human-in-the-loop.md](../user-stories/A3-human-in-the-loop.md). US-WEB-3 and US-WEB-4 describe the same rule seen from
the server and from the browser.

**Original general status: none of these routes was implemented on the server side.** Each story says where its
behaviour comes from:
- **Workstream A**: already described in `web-api.md` or `api-contract.md`.
- **Clarified**: Workstream A describes it, but a point was missing or wrong (see [web-api-alignment.md](../architecture/web/web-api-alignment.md)).
- **Extension**: absent from Workstream A's contract, proposed here; to be validated with Workstream A. If the extension is refused,
  the story says what the interface does instead.

> **Status on 2026-10-29:** the real server `sensai-web` ([ADR-0035](../decisions/0035-real-web-server.md)) now
> serves health, config, sessions (create, list, read, fork, delete, export, share), messages, confirm, answer,
> interrupt, profile (read only), facts and state (`src/sensai/web/server.py`). Stories touched by the merges of
> 2026-10-29 carry their own status line below. Statuses: ✅ checked with the real agent · ◐ partly ·
> 🎭 still simulated · ⏳ not checked yet. Today's changes were checked by automated tests (scripted model) and a
> headless browser **without** a model, never with the real agent: ◐ at best.

| Story | Subject | Source |
| --- | --- | --- |
| US-WEB-1 | Streamed answer | Workstream A |
| US-WEB-2 | Reasoning and tools | Workstream A |
| US-WEB-3 | Confirmation before a risky action | Clarified |
| US-WEB-4 | Disconnection during a confirmation | Workstream A |
| US-WEB-5 | Create and resume a session | Clarified |
| US-WEB-6 | List sessions and profile | Clarified |
| US-WEB-7 | Interrupt a generation | Extension |
| US-WEB-8 | Edit a message and fork | Extension |
| US-WEB-9 | Answer a question from the agent | Extension |
| US-WEB-10 | Export a session | Extension |
| US-WEB-11 | Share by link | Extension |
| US-WEB-12 | Usage and log | Extension |
| US-WEB-13 | Protected access | Clarified |
| US-WEB-14 | No secret in the stream | Extension |
| US-WEB-15 | Errors and robustness | Clarified |
| US-WEB-16 | Health and configuration | Extension |

---

## Answer and reasoning

### US-WEB-1 — See the answer arrive as it is written
**As** Camille, the developer asking the agent a question from the browser,
**I want** the answer to appear word by word instead of arriving in one block,
**so that** I do not wait blindly while the model works.

**Acceptance criteria:**
- `POST /api/sessions/{id}/messages` with `{"content": "..."}` answers `200` as `text/event-stream` and stays open for the whole turn.
- Each event is a `data: <JSON>` line followed by an empty line, with a `type` field among `token`, `thought`, `tool_call`, `tool_return`, `error`, `done`, `confirm_request`.
- The answer's text arrives in successive `token` events; concatenating their `text` gives the final answer.
- **`done` is always the last event**, including after an `error`, and the stream closes right after.
- `done.reason` is `final_answer`, `error` or `max_iterations` (the core stops after 6 model calls per turn).
- Empty or whitespace-only content is refused with `400` before opening the stream, without calling the model.

### US-WEB-2 — Understand what the agent is doing
**As** Camille, the developer who wants to check the agent's work,
**I want** to see its reasoning and each tool it calls, with the result,
**so that** I can correct it early if it goes wrong.

**Acceptance criteria:**
- Reasoning arrives as a single `thought` event per step, never word by word, and never mixed with `token`s.
- A `tool_call` (`id`, `name`, `arguments`) is always followed by a `tool_return` with the **same** `id`, even if two tools follow each other in the turn.
- A failing tool produces a `tool_return` with `ok: false` and **the turn goes on**: it is not an `error`.
- `error` means "this turn is lost": nothing follows except `done`.
- Unreadable call arguments (invalid JSON from the model) come back as a `tool_return` `ok: false`, without running the tool.

> **Status on 2026-10-29:** ◐ Partly, for an addition not in the criteria above: the server now also emits
> `{"type":"agent_handoff","from","to"}` when a `delegate_task` sub-agent starts, at each `team_task` relay
> (explorateur → developpeur → relecteur, send-backs included) and back to `"main"` before the tool's
> `tool_return` ([ADR-0047](../decisions/0047-real-agent-handoffs-in-the-web.md), proposed). Checked by `tests/web/test_handoffs.py` with a scripted
> model, not with the real model. Sub-agents' own steps are still not streamed.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): `delegate_task` and `team_task` relays were streamed, with the sub-agents' `subagent_step` events.

## Confirmation before a risky action

### US-WEB-3 — Allow or refuse before an action happens
**As** Camille, the developer who keeps control of her project,
**I want** no code to run and no file to be written without my explicit consent from the browser,
**so that** the agent cannot do anything irreversible without me.

**Acceptance criteria:**
- Before a tool whose mode is "ask", the stream contains a `confirm_request` event with an identifier, the tool name, its risk level (`read`, `network`, `write`, `execute`), a readable `summary`, the **complete** `arguments` (the exact code, the exact content) and `timeout_s`.
- The browser answers with `POST /api/sessions/{id}/confirm` with `{"confirm_id": "...", "approved": true|false}`; the response is `204`.
- The identifier field is called `confirm_id` **in the event as in the answer** (see the alignment: Workstream A's contract uses `id` in one and `confirm_id` in the other).
- Approved: the tool runs and a `tool_return` follows. Refused: the tool does not run and the `tool_return` reports the refusal (`ok: false`); the turn goes on.
- **No answer before `timeout_s` = refusal**, never acceptance. The delay is enforced by the gateway; the server does not count it again.
- An answer to an unknown, already resolved or expired `confirm_id` is ignored with no effect: `404` or `409`, never an execution.
- A confirmer that crashes or answers anything other than `true` is treated as a refusal.

### US-WEB-4 — Closing the tab must not run anything
**As** Camille, the developer who closes her tab in the middle of a confirmation,
**I want** the pending action to be abandoned,
**so that** I do not find anything executed in my absence.

**Acceptance criteria:**
- If the browser disconnects while a confirmation is pending, the answer is a refusal and the tool does not run.
- Disconnecting the stream interrupts the current turn on the server: no further model call or tool starts afterwards.
- A `POST /confirm` arriving after the disconnection is ignored.

## Sessions

### US-WEB-5 — Resume where I left off
**As** Camille, the developer working several days on the same project,
**I want** to create a session or resume an existing one, and find its history,
**so that** I do not have to explain the context again.

**Acceptance criteria:**
- `POST /api/sessions` returns `201` with `session_id`; with an existing `session_id` in the body, it resumes that session.
- The first message creates the session if none exists for the project: the client does not need an explicit call first (Workstream A's contract left this point open).
- `GET /api/sessions/{id}` returns the messages (`role`, `content`) in order. **It does not return a timestamp per message**: the storage (`SessionStore`) does not keep one, only `created_at` and `updated_at` for the whole session.
- A message whose turn fails (model unreachable, stream cut) is **not** saved: on resume, the history contains no half turn.
- An unknown session gives `404` with an error body `{"error", "code", "details"}`.
- Sessions are stored **per project**: only those of the configured project are visible.

> **Status on 2026-10-29:** ◐ Partly. The Memory page lists the real conversations with "Rouvrir", which opens the
> chat with the history; the next message continues that session (#44, uses `GET /api/sessions` and
> `GET /api/sessions/{id}`, no server change). The chat also has a conversation sidebar ("+ Nouvelle conversation",
> reopen). Checked in a headless browser against `sensai-web` **without** a model, not with the real agent.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): a conversation was listed, reloaded and continued (the agent remembered the function discussed), and reopened from the sidebar in the browser.

### US-WEB-6 — Find my sessions and my preferences
**As** Camille, the developer coming back to a project,
**I want** to list my sessions and manage my preference profile,
**so that** I can choose the conversation to resume and not repeat my habits.

**Acceptance criteria:**
- `GET /api/sessions` returns, for each session, `id`, `title`, `created_at`, `updated_at` and `message_count`, newest first.
- `GET /api/profile` returns the list of preferences; `POST /api/profile/preferences` adds one (empty or duplicate: ignored); `DELETE /api/profile` clears them all.
- The saved profile is injected into the system prompt of the next turn, as in the CLI.
- Purging sessions older than the retention period (30 days by default) stays the core's job: the server does not reimplement it.

> **Status on 2026-10-29:** ◐ Partly, with an addition not in the criteria: a conversation can now be deleted from
> the chat sidebar (confirmed inline) through `POST /api/sessions/{id}/delete` (token) → `204`; `409`
> `TURN_IN_PROGRESS` while a turn runs; `404` if unknown ([ADR-0049](../decisions/0049-hand-written-markdown-rendering.md), proposed). Known limit:
> `SessionStore.delete` does not VACUUM, so the deleted text stays in the SQLite file's free pages until the next
> VACUUM (the retention purge does one). Checked by tests, not with the real agent. Difference with the criteria:
> the server exposes only `GET /api/profile`; `POST /api/profile/preferences` and `DELETE /api/profile` are not
> in `server.py`.
>
> **Update on 2026-10-29:** ◐ The two routes now exist, with one difference: clearing is `POST /api/profile/forget`
> (not `DELETE /api/profile`), because the server only allows `GET` and `POST` (CORS). `POST /api/profile/preferences`
> (`{"text"}`, 500 characters at most) returns the profile; `400 TOO_MANY_PREFERENCES` above 50. The Memory page uses
> them, and shows the real profile and facts. The VACUUM limit is fixed: `SessionStore.delete` now runs `VACUUM`
> (`test_deleting_a_session_also_erases_its_text_from_the_file`). Checked by tests, not with the real agent.

> **Update on 2026-11-01:** ◐ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): a preference "always answer in English" added through the API was followed, but on the first attempt a French few-shot example won (finding 3); deleting a conversation returned 204 and removed its text from `sessions.db`, and "Tout oublier" worked in the browser.

## Conversation control

### US-WEB-7 — Stop the agent and redirect it
**As** Camille, the developer whose agent is heading the wrong way,
**I want** to stop it mid-generation, or give it a new instruction without waiting,
**so that** I do not waste time or compute.

**Acceptance criteria:**
- `POST /api/sessions/{id}/interrupt` stops the current turn: no further model call or tool starts, and the stream ends with `done`.
- The stop reason can be told apart from a complete answer: **extension requested from Workstream A**: `done.reason = "interrupted"`.
- Interrupting with no turn in progress answers `204` and has no effect.
- The partial answer already sent is not saved as a complete answer in the history.
- Sending a new message during a turn is refused with `409`, unless the interface interrupts first: one turn at a time per session.
- *If the extension is refused*: the interface closes its connection; the server detects the disconnection (US-WEB-4) and abandons the turn.

> **Status on 2026-10-29:** ◐ Partly. Besides the "■ Stop" button, pressing Escape in the message field now
> stops the answer too (#103). Checked by frontend tests, not with the real agent.

### US-WEB-8 — Explore another direction without losing the first
**As** Camille, the developer who phrased a request badly,
**I want** to edit a past message and get a new answer while keeping the old one,
**so that** I can compare two directions.

**Acceptance criteria:**
- `POST /api/sessions/{id}/fork` with `{"at_message": n}` creates a **new session** whose history stops just before message `n`, and returns its `session_id`. The original session is not modified.
- A branch is therefore a session: it appears in `GET /api/sessions`, with the same storage mechanism; **no change to the core is needed**.
- An `at_message` outside the history gives `400`.
- *If the extension is refused*: the interface keeps its branches in page memory and loses them on reload; it says so.

> **Status on 2026-10-29:** ◐ Partly. Editing a message of a conversation reopened from the Memory page forks at
> the right index (#44). Checked in a headless browser without a model, not with the real agent.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): a fork at 2 messages gave a conversation with 2 messages.

### US-WEB-9 — Answer the agent in a form
**As** Camille, the developer whose agent is missing a piece of information,
**I want** to answer it through a form rather than retyping free text,
**so that** I save time and avoid misunderstandings.

**Acceptance criteria:**
- The agent asks for information through an `ask_user` **tool** (risk `read`), not through a special core event: the core knows nothing about the interface.
- The server emits a `question` event (`question_id`, `title`, `fields`) in the open stream; `fields` describes each field (text, choice, checkbox).
- The browser answers with `POST /api/sessions/{id}/answer` with `{"question_id": "...", "values": {...}}`; the response is `204`.
- No answer before the delay, or disconnection: the tool returns `ok: false` ("no answer"); the agent goes on or concludes, but does not guess an answer.
- Values are validated against the announced fields: an unknown field or a wrong type gives `400`.
- *If the extension is refused*: the interface replaces the form with a question asked in the conversation, and the answer goes as an ordinary message.

> **Status on 2026-10-29:** ◐ Partly. Built as described ([ADR-0046](../decisions/0046-ask-user-tool.md), accepted on 2026-11-01; #99): tool
> `ask_user(title, fields)` (risk `read`, at most 8 fields of kind `text`, `choice` with 2 to 12 options, or
> `toggle`; an invalid form is a tool failure the model can fix). The `question` event also carries `timeout_s`;
> the server waits at most 100 s. `POST /answer` → `204`; invalid values → `400` `INVALID_ANSWER` (the question
> stays open); unknown or expired question → `404` `QUESTION_NOT_FOUND`. No answer (timeout, interrupt, tab closed)
> makes the tool fail and tell the model not to guess. The tool is also available in the CLI (asked in the
> terminal), not in `sensai-schedule`, and not to the `team_task` roles. Checked by tests with a scripted model,
> not with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): the `question` event was answered through the API and in the page, and an unanswered form expired after 100 s with the agent saying what was missing.

## Leaving the session

### US-WEB-10 — Keep a record of the session
**As** Camille, the developer who must report on her work,
**I want** to download a session as JSON or Markdown,
**so that** I can archive it or pass it on.

**Acceptance criteria:**
- `GET /api/sessions/{id}/export?format=json|md` returns the file with the right `Content-Type` and a download `Content-Disposition`.
- Exporting an empty session is a valid file, not an error.
- An unknown `format` gives `400`.
- PDF is not produced by the server: the interface uses the browser's print function.
- Export goes through the same secret filters as the stream (US-WEB-14).

### US-WEB-11 — Show a session to someone without an account
**As** Camille, the developer who wants to show her work to a colleague,
**I want** to generate a read-only viewing link,
**so that** they can read the session in a browser without installing anything.

**Acceptance criteria:**
- Sharing is **disabled by default** and explicitly requested: `POST /api/sessions/{id}/share` returns an opaque URL (random token, never the session identifier).
- The link is read-only, cannot act on anything, and exposes neither the tools, nor the configuration, nor other sessions.
- The link can be revoked (`DELETE /api/sessions/{id}/share`) and expires after a finite duration announced at creation.
- Shared content is filtered for secrets like the stream (US-WEB-14).
- It is the only place where a page is readable **without authentication**; it is a documented exception to US-WEB-13, not a flaw.

> **Status on 2026-10-29:** ◐ Partly ([ADR-0048](../decisions/0048-share-links.md), accepted on 2026-11-01; #101). What was built:
> `POST /api/sessions/{id}/share` (token) → `201` `{"url":"/share/<token>","token","expires_at"}`; empty session →
> `400` `EMPTY_SESSION`. The page is a snapshot of user and assistant messages only, passed through `filter_output`,
> stored under the SHA-256 of a random token, expiring after 7 days. `GET /share/<token>` needs no token, serves
> escaped static HTML with no script (CSP `default-src 'none'`, `noindex`, `no-referrer`, `no-store`); unknown,
> revoked or expired links all give the same 404 page. Differences with the criteria: there is no server setting
> that disables sharing — a link exists only when the user clicks "Create a share link", and it is reachable
> only by whoever can reach `sensai-web` (127.0.0.1 by default); revocation is
> `POST /api/shares/<token>/revoke` (→ `204` / `404` `SHARE_NOT_FOUND`) instead of `DELETE /api/sessions/{id}/share`,
> and the interface has no revoke button yet. Checked by tests, not with the real agent.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): the public page was read without a token, and returned 404 after revocation.

## Observability

### US-WEB-12 — See what a session costs and does
**As** Camille, the developer monitoring the agent,
**I want** to know the token usage, each tool's duration and the failures,
**so that** I can spot drift without rereading every line.

**Acceptance criteria:**
- A `usage` event (`prompt_tokens`, `completion_tokens`, `duration_ms`) may accompany the end of a turn. **Extension requested from Workstream A**: the current contract left the question open.
- A tool's duration is measured between its `tool_call` and its `tool_return`; the interface can compute it itself, the server has nothing to add.
- *If the extension is refused*: the context gauge stays an estimate made by the interface, labelled as such; it is not presented as a measurement.
- The displayed log contains only what actually went through the stream: no invented data.

## Security and robustness

### US-WEB-13 — Nobody but me drives my agent
**As** Camille, the developer running the server on her machine,
**I want** the API to refuse any unauthenticated access,
**so that** nobody can run code on my machine.

**Acceptance criteria:**
- Every API route, SSE stream included, answers `401` without a valid token, before any processing.
- The token is generated at startup, shown once in the developer's console and never written to logs or into a URL.
- The server listens **only on the local machine** by default; opening it to the network requires an explicit option and a warning.
- Allowed origins (CORS) are a closed list; no origin is accepted by default apart from the interface itself.
- A wrong, missing or malformed token gives the same `401` response, without saying which case it is.
- The remote Ollama pod is not publicly reachable (rule from ADR-0004, taken over by Workstream A).

### US-WEB-14 — No secret leaves through the stream
**As** Camille, the developer whose project contains keys,
**I want** no secret to go through the browser,
**so that** they are not exposed in a shared tab, a screenshot or an export.

**Acceptance criteria:**
- A tool's result goes through Workstream B's output filters (secrets, personal data) before being sent as `tool_return`.
- Export and sharing use the same filters.
- **Known limit not to hide**: the text written by the model (`token`, `thought`) is not filtered by the gateway, which only sees tools. If the model copies a secret into its answer, it appears. Whether to filter streamed text is to be decided with Workstream B; until then, it is documented as a residual risk.

### US-WEB-15 — Errors I can understand
**As** Camille, the developer whose model is sometimes unreachable,
**I want** clear errors and a server that does not crash,
**so that** I know what to do without reading logs.

**Acceptance criteria:**
- Model unreachable **before** the stream: `503` with `{"error","code","details"}`. **During** the stream (already open): an `error` event then `done` with `reason: "error"`.
- Invalid JSON body: `400`. Message too long: `413`. A turn already in progress on the session: `409`.
- No Python traceback or file path appears in an error message sent to the browser.
- A slow or cut client does not block other sessions: an agent turn does not freeze the server (the core is synchronous and blocking, so it runs outside the event loop).
- Two sessions can run at the same time without mixing their events or their confirmations.

### US-WEB-16 — Know who I am talking to and what is plugged in
**As** Camille, the developer who opens the web interface,
**I want** to know the server's state and its useful configuration,
**so that** I can show the model, the list of tools and a clear message if the server is down.

**Acceptance criteria:**
- `GET /api/health` answers `200` without authentication and reveals nothing but "ok" and the version.
- `GET /api/config` (authenticated) returns the model, the system prompt's name and version, the list of visible tools with their risk level and mode (allow, ask, deny). **It never returns an Ollama server address, a token, or a file path.**
- A tool that is disabled or denied by the policy does not appear in the list of offered tools.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-WEB-1 | ✅ | `web/server.py`, `web/runtime.py` | `tests/web/test_web_facade_spike.py` (`test_streamed_answer_and_done_last`, `test_empty_or_too_long_message_is_rejected_before_the_stream`) | The limit is no longer a fixed 6: 6 by default, set by `max_iterations` (ADR-0057). Tokens now arrive line by line (answer filter, ADR-0058) |
| US-WEB-2 | ✅ | `web/runtime.py` | `tests/web/test_web_facade_spike.py::test_tool_call_and_return_share_the_same_id`, `tests/web/test_handoffs.py` |  |
| US-WEB-3 | ✅ | `execution/web_confirmation.py`, `web/server.py` | `tests/execution/test_web_confirmation.py`, `tests/web/test_web_facade_spike.py::test_the_risky_tool_runs_only_after_approval` |  |
| US-WEB-4 | ✅ | `execution/web_confirmation.py` | `tests/web/test_web_facade_spike.py::test_closing_the_tab_during_confirmation_runs_nothing` |  |
| US-WEB-5 | ✅ | `web/server.py`, `knowledge/memory.py` | `tests/web/test_web_facade_spike.py` (`test_a_successful_turn_enters_the_history`, `test_unreachable_model_gives_error_then_done_and_nothing_is_saved`, `test_unknown_session_gives_404_with_an_error_body`) |  |
| US-WEB-6 | ◐ | `web/server.py` (`/api/profile`) | `tests/web/test_server.py` | Clearing is `POST /api/profile/forget`, not `DELETE /api/profile` (written above) |
| US-WEB-7 | ◐ | `web/server.py` (`/interrupt`) | `tests/web/test_web_facade_spike.py::test_interrupt_ends_with_done_interrupted_without_saving_the_turn`, `tests/web/test_journal_quality.py::test_a_second_run_during_the_first_returns_409` | Stop works; sending during a turn is refused (`409`), the interface does not interrupt first |
| US-WEB-8 | ✅ | `web/server.py` (`/fork`) | `tests/web/test_server.py` (fork test) |  |
| US-WEB-9 | ✅ | `web/questions.py`, `tools/ask_user_tool.py` | `tests/web/test_questions.py` |  |
| US-WEB-10 | ◐ | `web/server.py` (`/export`) | `tests/web/test_server.py::test_export_filters_secrets` | See X3 US-X3-1 |
| US-WEB-11 | ✅ | `web/shares.py` | `tests/web/test_shares.py` |  |
| US-WEB-12 | ◐ | `web/runtime.py` (`usage`), `observability/journal.py` | `tests/web/test_real_features.py`, `tests/web/test_journal_quality.py` | `usage` carries estimated `used`/`budget`/`num_ctx`, not Ollama's `prompt_tokens`/`completion_tokens`; labelled as an estimate |
| US-WEB-13 | ✅ | `web/server.py`, `web/cli.py` | `tests/web/test_web_facade_spike.py::test_token_required_everywhere_except_health`, `tests/web/test_server.py::test_cors_closed` |  |
| US-WEB-14 | ✅ | `execution/gateway.py`, `execution/guardrails.py` (`StreamRedactor`) | `tests/core/test_agent.py::test_a_secret_written_by_the_model_is_masked_even_split_into_chunks`, `tests/web/test_server.py::test_export_filters_secrets`, `tests/web/test_shares.py` | The "known limit" above is fixed on 2026-11-01: `token` text is filtered line by line (ADR-0058) and `thought` text as one block (`tests/core/test_agent.py::test_the_displayed_reasoning_is_filtered_too`) |
| US-WEB-15 | ✅ | `web/server.py` | `tests/web/test_web_facade_spike.py` (`test_unreachable_model_gives_error_then_done_and_nothing_is_saved`, `test_one_turn_at_a_time_per_session`, `test_two_parallel_sessions_do_not_mix_their_confirmations`) |  |
| US-WEB-16 | ✅ | `web/server.py` (`/api/health`, `/api/config`) | `tests/web/test_server.py` |  |
