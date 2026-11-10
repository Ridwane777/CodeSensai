# ADR-0042 — Persona (A5): config-driven profiles, switchable mid-session

- **Status**: Accepted
- **Date**: 2026-10-26
- **Deciders**: Fresnel (Lot A)
- **Lot concerned**: A (`knowledge/`, `cli.py`)

## Context

[A5] Persona requires that the agent's name, tone, role, and response scope
be configurable without touching the code, and that the system manage
several distinct profiles, switchable at runtime without clearing the
conversation history.

Constraints from the repo: no new entry point (same rule as A2, ADR-0037);
the system prompt is already rebuilt from several fragments at every turn
(`cli.py: system_prompt()` — base prompt, resumed-session note, project
state, remembered facts); session history (`History.turns`) must stay
untouched by anything that isn't a user/assistant message.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Persona hardcoded as Python objects, picked by a CLI flag at startup | Simple, no new file format | Changing or adding a persona means editing code and restarting; no mid-session switch (violates the catalogue requirement) |
| Config-driven profiles (`config.json["personas"]`) + a chat command (`/persona use <id>`) that only changes a mutable label read by `system_prompt()` | No new entry point; reuses the existing per-turn prompt rebuild; switching never touches `History.turns`, so context survives, as required | The active persona is session-local state, not persisted — resuming a session later starts back on the default persona |
| Store the active persona inside the saved session (one more column in `sessions.db`) | Switch persists across `--session` resumption | Couples M1 (session persistence, ADR-0007) to A5; schema migration on a database that already ships; not needed by the catalogue's wording ("mid-session"), only resuming later |

## Decision

Personas are declared in `config.json`, in a new `personas` section (`default`
+ a list of `profiles`, each with `id`, `name`, `role`, `tone`, `scope`),
loaded once at startup by `PersonaStore.from_config()` (`knowledge/persona.py`).
A broken or incomplete profile stops the CLI at startup, the same way a bad
`tools`/`files` section already does in `config.py` — a misconfigured
persona must never pass for a working one.

The active persona is just a string kept in a local variable inside
`cli.main()`, changed by the chat command `/persona use <id>`
(`handle_persona_command()`, same shape as `/state` and `/facts`). Its
`as_prompt()` text is one more fragment folded into `system_prompt()`,
alongside the project state and remembered facts. Switching never writes to
`History.turns`: the model keeps every earlier message, only the system
prompt for the next turn changes — this is what lets the agent "change
persona mid-session while retaining full context", as the catalogue asks.

Without a `personas` section, a single neutral default persona is used
(`PersonaStore.from_config(None)`): a project that doesn't configure
anything keeps behaving exactly as before this feature.

## Consequences

- ✅ No new entry point, no new storage: reuses the existing per-turn prompt
  rebuild and the existing command-handling pattern (`/state`, `/facts`).
- ✅ Switching a persona is free of side effects on the conversation: the
  session history, the RAG index, the cache and the state document are all
  untouched.
- ❌ The active persona is not remembered across a session resumption
  (`--session <id>` after quitting): the next run starts back on the
  default persona. The catalogue only asks for a switch "mid-session", so
  this is accepted for now rather than coupling A5 to M1's schema.
- ❌ A persona only changes the system prompt text — it does not restrict
  which tools the agent can call (a "math tutor" persona can still call
  `run_code`). Per-persona tool restriction would reuse `ToolPreferences`
  (already in `config.py`) but is left for a later iteration if the need is
  confirmed, not forgotten.
- ❌ The web server (`src/sensai/web/runtime.py`) does not read
  `settings["personas"]`: it builds its own system prompt, so a persona
  configured in `config.json` changes the CLI but not the web chat — even
  though [ADR-0035](0035-real-web-server.md) asks for the same agent on
  both sides. Nothing in the web interface exposes `/persona` either. Wiring
  it means giving `Runtime` the same `PersonaStore` and an active-persona
  field per web session; not done here, left as an open gap rather than
  assumed away.
- ❌ Sub-agents (`delegate_task`, `team_task`) only get the active persona
  where their `system_prompt` callable includes it. In the CLI it does:
  `DelegateTool` receives `cli.py`'s own `system_prompt()`, so a sub-agent
  started after `/persona use` inherits the active persona (covered by
  `tests/test_cli_persona.py`). In the web server and in `sensai-schedule`
  (X5) it does not, for the same reason as the line above: those entry
  points build their own prompt without any persona.
- ❌ `sensai-schedule` (X5) does not read `settings["personas"]` either: an
  unattended scheduled task always runs without a persona.
- Follow-up: if automatic persona routing (keyword- or topic-based, as in
  the catalogue's support-triage example) turns out to be needed, revisit
  without rewriting this ADR.
