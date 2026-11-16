# Known limits

[Docs map](README.md) · see also: [features](features.md), [backlog](backlog.md)

What does not work yet, or works with conditions, as of the last full trial.

- **Web interface, real model**: the web additions merged on 2026-10-29 and
  2026-10-31 were tried with `qwen3-coder:30b` on 2026-11-01
  ([trial](performance/trials/trial-2026-11-01.md)). The project index not being refreshed during a session
  (finding 1) is fixed (PR #108). Findings 2–6 were then addressed and re-checked with the
  real model (see "Re-check after the fixes" in the trial):
  - `team_task`: a file created in the wrong place is sent back and never validated (fixed).
  - Language preference vs a French few-shot example: fixed on 2026-11-01 afternoon
    (profile last in the prompt, preferences repeated next to the example, example not
    attached when the question is its own); re-checked once per question with the real model.
  - Facts saved in a deleted conversation stay; they can now be forgotten from the
    Memory page, and the delete confirmation says so (fact history keeps a trace).
  - Answer text split by tool calls is saved as paragraphs, a rewritten or rephrased part
    only once (fixed); the live stream still shows both parts as they arrive.
  - Inventing a value never read: system prompt v3 forbids it; re-checked once, the model
    said it did not know (mitigated: depends on the model).
- **Full trial of 2026-11-01 afternoon** ([report](performance/trials/trial-2026-11-01-evening.md)):
  every feature passed with the real model (API, global run, browser). The facts and
  state-document blocks no longer push the model to call `recall_facts`,
  `update_state` or `save_fact` for a simple question. Each check is one try: the
  model's behaviour can still vary.
- **Web additions of 2026-10-29**: token
  counts are estimates
  (characters / 4); sub-agent step output is cut at 600 characters.
- **A7 visible in the web** (2026-11-01): the Prompts page lists the real
  few-shot examples (`GET /api/fewshot`) and the chat shows which example
  inspired an answer. Detail: [simulated-vs-real.md](architecture/web/simulated-vs-real.md).
- **Personas (A5) and prompt versions (A4) in the web** (Workstream A, 2026-11-01, checked
  with `qwen3-coder:30b`): the persona and the prompt trial are per conversation and
  held in server memory, not saved. Keyword routing and session-only personas were removed (ADR-0056).
  Activating a prompt version for everyone stays `sensai-prompt use`; the web never
  writes the registry.
- **Scheduler (X5) in the web**: the Planning page edits the tasks, but only
  `sensai-schedule loop` (or `run-due`) runs them; the web server runs none.
- **Terminal-only chat commands**: `/schedule` and `/eval` typed in the web chat
  answer that they are used in the terminal (`TERMINAL_ONLY` in `src/sensai/web/runtime.py`).
- **Evaluation (EV1) in the web**: on demand only (one model call per click),
  never automatic at each turn.
- **MCP (T1)**: tried with the repo's test server and, on 2026-11-01, with the
  published `mcp-server-time` server (issue #45): the model called it by itself when
  `web_search` was disabled.
- **Logging (EV3)**: the turn journal (`<data_dir>/journal.db`,
  [ADR-0053](decisions/0053-server-side-turn-journal.md)) is tested with a
  scripted model and was checked with the real model on 2026-11-01; durations are wall-clock (a
  tool's duration includes the user's confirmation time); the CLI does not record
  sub-agent tool calls yet.
- **Structured output (T5)** is a terminal command (`/structured`), not a web
  feature; the Quality page only points to it.
- **Adversarial gaps**: 19 known gaps of the EV4 corpus remain (obfuscated
  injections and secrets, some sensitive files, look-alike search results);
  see the [backlog](backlog.md).

Tracking: the repo's GitHub issues.
