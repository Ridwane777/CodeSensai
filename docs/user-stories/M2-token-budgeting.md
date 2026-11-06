# M2 — Token Budgeting & Semantic Compression

See [ADR-0045](../decisions/0045-token-budget-sliding-summary.md) for the
design (approximate token count, sliding-window summary via the chat model
itself, never touching the saved session). The session-persistence half of
M2's old scope (resuming a conversation across runs) is delivered by M1 —
see [M1-session-persistence.md](M1-session-persistence.md).

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `/context`: ✅ with both set-ups (< 1 s).

## US-M2-1 — A long session keeps working instead of hitting a wall (was User Story 1 of M2-token-budgeting.md)
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer in a long debugging session**, I want **the agent to keep
answering correctly even once our conversation has grown very long**, so
that **I don't have to start a new session or watch the agent fail once we
cross some invisible limit**.

### Acceptance criteria

- Once the estimated size of what would be sent to the model — including
  the project passages and the few-shot example attached to the question —
  crosses a configurable budget (`token_budget_max`, by default derived
  from the context window `num_ctx` minus a margin for the answer: 6192
  tokens for the default 8192 window, an estimate, see ADR-0045), the
  oldest turns are condensed into one summary before the next question is
  sent — not after the model has already failed to answer.
- The summary is produced by the same chat model already in use, in a
  separate call, before the real question's own call.
- The most recent turns (`token_budget_keep_recent`, default 6) are never
  summarized: the immediate context of the current question stays exact.
- If the summary can't be produced (the model is unreachable), the turn
  still proceeds with the uncompressed history — the feature degrades
  without blocking the conversation, and the user is told.
- The same budget applies in the web interface: a long web session is
  summarized the way a long CLI session is.

## US-M2-2 — Resuming later still finds the whole conversation (was User Story 2 of M2-token-budgeting.md)
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer who closes the CLI and comes back the next day**
(`--session <id>`, feature M1), I want **my resumed conversation to still
contain everything we said, not a compacted version**, so that **a detail
condensed away for an earlier question is still there if I need it later**.

### Acceptance criteria

- The summarization in US-M2-1 only changes what is sent to the model
  for the current question; it never rewrites what is saved to the
  session (`SessionStore`, M1).
- Resuming a session later (`sensai --session <id>`) shows the exact same
  message history it would have shown before any compression happened —
  only a long enough *new* conversation on top of it may trigger
  compression again, independently, from the full history.

## US-M2-3 — Ollama never cuts the conversation without anyone noticing (was User Story 3 of M2-token-budgeting.md)
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer whose conversation (or whose project passages) is larger than the
model's context window**, I want **the agent to size its requests to that
window, and to tell me when it cannot**, so that **an answer is never quietly
built on a context that Ollama silently truncated**.

### Acceptance criteria

- The context window (`num_ctx`, default 8192, `--num-ctx` or `config.json`)
  is sent to Ollama with every chat call: the CLI conversation, the web chat,
  `/structured`, the sub-agents (`delegate_task`, `team_task`), the
  reranker, the evaluation commands and scheduled tasks. Without it, Ollama
  falls back to its own default (2048 or 4096 tokens) and truncates.
- The default token budget follows the window that was actually requested:
  `--num-ctx 4096` lowers it, `--num-ctx 32768` raises it. A budget at or
  above the window is refused at startup.
- When a turn is over budget but nothing can be summarized (one very large
  message, or fewer turns than the ones always kept exact), it is sent as is
  and a warning says that Ollama may truncate it — in the CLI, and as a
  notice in the web interface.

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): every turn sends a `usage` event (`used`, `budget`, `num_ctx`, `estimated: true`) before the answer, shown as the token bar with the context %; counts are **estimated** (characters / 4), not the model's own. When the sliding summary ran, a `compression` event (`saved_tokens`) shows the notice. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): `usage` events were sent (token bar 867 / 6 192 after the first answer), and compression ran at the 10th long message (`used` 5 699 → 3 093) with the agent still knowing what it had received.

---

## Part merged from `M2-context-management.md` on 2026-11-02: M2 — Context and history management

> Filed as A6 when it was created; A6 is Semantic Cache in the catalogue.
> US-M2-4 is delivered by M1 ([M1-session-persistence.md](M1-session-persistence.md));
> US-M2-5 (a context that does not exceed the model's limits) became
> [M2] Token Budgeting & Semantic Compression, delivered on 2026-10-27 — see
> US-M2-1 to US-M2-3 above and
> [ADR-0045](../decisions/0045-token-budget-sliding-summary.md).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

## US-M2-4 — The conversation history persists between sessions (was User Story 1 of M2-context-management.md)
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer in the middle of a long debugging session**, I want **my conversation to be saved and to be able to resume it later**, so that **I can continue a 2-hour debugging session without losing the context**.

### Acceptance criteria

- Each session has a unique ID and a timestamp
- The messages (user + agent) are saved in a database
- When I restart the app, I can resume an existing session
- The agent has access to the whole past history (no arbitrary limit)

## US-M2-5 — The model's context stays readable and consistent (was User Story 2 of M2-context-management.md)
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer who relies on the agent's answers**, I want **the system prompt and the messages to be well organised** before they are sent to the model, so that **the model receives a clear instruction and a structured history**.

### Acceptance criteria

- The system prompt is clearly separated from the history
- The messages are in chronological order
- The roles (user/assistant) are always correct
- The context does not exceed the model's limits (or a warning is issued)

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-M2-1 Long session | ✅ | `knowledge/compression.py`, `cli.py`, `web/runtime.py` | `tests/knowledge/test_compression.py`, `tests/test_cli_compression.py`, `tests/web/test_runtime_budget.py` | Token counts are estimates (characters / 4) |
| US-M2-2 Resume keeps everything | ✅ | `knowledge/compression.py` (does not touch `SessionStore`) | `tests/test_cli_compression.py` |  |
| US-M2-3 `num_ctx` always sent | ✅ | `core/ollama_client.py`, `core/agent.py`, `config.py` | `tests/core/test_ollama_client.py::test_stream_chat_transmet_num_ctx`, `tests/web/test_runtime_budget.py::test_les_sous_agents_du_web_recoivent_num_ctx`, `tests/scheduling/test_schedule_cli.py::test_num_ctx_de_la_config_part_avec_l_agent_planifie`, `tests/core/test_structured.py::test_num_ctx_part_dans_les_options_de_l_appel`, `tests/knowledge/test_retrieval.py::test_le_reclassement_envoie_num_ctx_quand_il_est_donne` |  |
| US-M2-4 History persists | ✅ | `knowledge/memory.py` (SQLite) | `tests/knowledge/test_memory.py::test_une_session_survit_a_la_fermeture`, `tests/test_cli_persistence.py` | Delivered by M1 |
| US-M2-5 Readable context | ✅ | `core/history.py`, `core/context_view.py` (`/context`), `knowledge/compression.py` | `tests/test_cli_compression.py::test_describe_context_montre_le_prompt_exact_et_les_reglages`, `tests/web/test_server.py::test_context_montre_le_prompt_exact_sans_appeler_le_modele`, `tests/web/test_runtime_budget.py::test_un_contexte_trop_gros_pour_etre_reduit_avertit` | `/context` (ADR-0058) shows the exact messages sent, `num_ctx`, the budget and the generation settings |
