# A5 - Persona

See [ADR-0042](../decisions/0042-configurable-personas.md) for the core
design (config-driven profiles, switch without losing context) and
[ADR-0043](../decisions/0043-persona-enhancements.md) for the
enrichments below user story 2 (keyword routing, per-persona tool
restriction, session-only personas).

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `/persona list` and `GET /api/personas`: ✅ with both set-ups (< 1 s).

## User Story 1: Configuring a persona without touching the code
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** "so that" for the scenario: so that **the team gets a "reviewer" persona that reads and reviews code without being able to write files, set up once in `config.json` with no code change** (step S0). The legal-assistant and math-tutor example came from the feature catalogue, not from Marc's needs.

As **Marc, the lead who sets CodeSensai up for a specific use case**, I want **the agent's
name, tone, role and response scope to be configurable in `config.json`**,
so that **the same system becomes a legal assistant or a math tutor without
a code change**.

### Acceptance criteria

- A `personas` section in `config.json` lists one or more profiles (`id`,
  `name`, `role`, `tone`, `scope`) and a `default` id.
- An incomplete profile, a duplicate `id`, or an unknown `default` stops the
  CLI at startup with a clear error - it never silently falls back to a
  partial persona.
- Without a `personas` section, the agent keeps working with a single
  neutral default persona (no code change required for existing projects).
- The active persona's `role`, `tone` and `scope` are part of the system
  prompt sent to the model.

## User Story 2: Switching persona mid-conversation without losing context
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** "so that" for the scenario: so that **Camille can have her change checked by the "reviewer" persona in the same conversation, without restarting the chat or retyping what the agent already knows** (step S9). The support and tutoring examples came from the feature catalogue, not from Camille's day.

As **Camille, the developer chatting with the agent**, I want to **switch which persona is
active during an ongoing conversation**, so that **a support flow can hand
off from a technical agent to a commercial one, or a tutoring platform can
move from one subject's agent to another's, without restarting the chat**.

### Acceptance criteria

- `/persona` shows the currently active persona.
- `/persona list` lists every configured persona, marking the active one.
- `/persona use <id>` switches to that persona for the next turns; an
  unknown `id` leaves the active persona unchanged and shows an error.
- After a switch, the full prior conversation (`History.turns`) is
  unchanged: the model still has access to everything said before the
  switch.

## User Story 3: Routing to the right persona automatically
> **Update on 2026-11-06:** no scenario step: withdrawn ([traceability](../design/traceability.md#features-dropped-or-changed-along-the-way)).

> **Withdrawn on 2026-11-02** ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 4). Kept below for the record.

As **Marc, the lead who sets up several personas for the team**, I want **the right persona
to activate on its own when a question matches its topic**, so that **a
client question about a contract reaches the legal persona, and a question
about derivatives reaches the math tutor, without anyone typing a
command**.

### Acceptance criteria

- A persona can declare a list of `keywords` in `config.json`.
- Before a question reaches the model, if one of a non-active persona's
  keywords appears in it, that persona becomes active for this and later
  turns - the switch is announced to the user.
- A persona without `keywords` is never triggered automatically; it still
  works with `/persona use`.
- A chat command (`/persona …`) or a cached answer never triggers this
  routing - only a question that actually reaches the model.

## User Story 4: Keeping a persona from using tools it shouldn't
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Marc, the lead who deploys a restricted persona** (e.g. a math tutor), I want
**that persona to be unable to call tools outside its purpose** (e.g.
executing code), so that **the agent's scope stays what the persona
promises, not just what it says in its tone**.

### Acceptance criteria

- A persona can declare `tools.disabled` (a list of tool names) in
  `config.json`.
- While that persona is active, those tools are neither offered to the
  model nor executable through the gateway, on top of whatever
  `config.json`'s global `tools` section already disables.
- A persona can never re-enable a tool the global configuration disabled -
  restrictions only ever add up.
- Switching back to a persona without `tools.disabled` restores exactly
  the global configuration's tool set.

## User Story 5: Trying out a persona without editing a file
> **Update on 2026-11-06:** no scenario step: withdrawn ([traceability](../design/traceability.md#features-dropped-or-changed-along-the-way)).

> **Withdrawn on 2026-11-02** ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 4). Kept below for the record.

As **Camille, the developer in the middle of a conversation**, I want to **define a new
persona from the chat itself**, so that **I can try a quick variant (a
different tone, a narrower scope) without stopping to edit `config.json`
and restart**.

### Acceptance criteria

- `/persona add <id> <name> <role> <tone> <scope>` creates a persona
  usable immediately with `/persona use <id>`, in the current session.
- Trying to reuse an existing `id` is refused with a clear error; nothing
  already configured is overwritten.
- The command's own reply says the persona is session-only: it will be
  gone on the next `sensai` run unless added to `config.json` by hand.

## User Story 6: Choosing the persona of a conversation in the web interface
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** "so that" for the scenario: so that **Camille can hand her open conversation to the "reviewer" persona from the page she is already working in, and its disabled tools are refused there too** (step S9).

*Update on 2026-11-01 ([ADR-0054](../decisions/0054-personas-in-the-web.md)):
◐ tested with pytest and vitest, not yet with the real model.*

As **Camille, the developer using the web interface**, I want to **pick the persona of the
conversation I have open from the "Agent actif" selector or the Agents page**,
so that **I get the same personas as in the CLI without opening a terminal**.

### Acceptance criteria

- With the real server, the selector and the Agents page list the personas of
  `config.json`, with their role, tone, scope and disabled tools; the default
  and the active one are marked.
- Choosing a persona applies to the next turn of that conversation only;
  another conversation keeps its own persona, a new one starts from the default.
- The persona cannot be changed while a turn runs in that conversation (409).
- The choice is held by the server while it runs: it is not saved, as in the
  CLI.
- Persona creation and keyword routing are not offered in the web (CLI-only).

## User Story 7: A restrictive persona stays restrictive in the web, sub-agents included
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

*Update on 2026-11-01: ◐ tested with a scripted model (pytest), not yet with
the real model.*

As **Marc, the lead who deploys a restricted persona**, I want **its disabled tools to
be refused in the web too, including for sub-agents it delegates to**, so that
**`delegate_task` is not a way around the restriction**.

### Acceptance criteria

- With a persona that disables `write_file`, the tool is neither offered nor
  executed for the main agent, and a `delegate_task` sub-agent cannot write
  either; no file is created.
- The sub-agent's system prompt contains the persona block.
- A persona that disables tools neither reads nor feeds the answer cache.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| Story 1 Configure | ✅ | `knowledge/persona.py` | `tests/knowledge/test_persona.py` (`store_charge_les_profils_de_la_config`, `profil_incomplet_refuse`), `tests/test_config.py::test_malformed_persona_stops_the_cli_with_a_message` |  |
| Story 2 Switch | ✅ | `knowledge/persona.py`, `cli.py` | `tests/test_cli_persona.py` (`persona_use_change_le_prompt_systeme_au_tour_suivant`, `persona_use_laisse_lhistorique_intact`) |  |
| Story 3 Routing | - | - | `tests/knowledge/test_persona.py::test_keyword_routing_is_explicitly_refused` | Withdrawn on 2026-11-02 (ADR-0056, item 4): the scenario does not need it; a `keywords` field is now refused |
| Story 4 Restrict tools | ✅ | `knowledge/persona.py`, `cli.py` | `tests/test_cli_persona.py` (`persona_avec_outils_restreints_les_retire`, `delegate_task_refuse_un_outil_desactive_par_la_persona`) |  |
| Story 5 Try without editing a file | - | - | `tests/knowledge/test_persona.py::test_persona_add_no_longer_exists` | Withdrawn on 2026-11-02 (ADR-0056, item 4): personas are defined in `config.json` |
| Story 6 Web choice | ✅ | `web/runtime.py`, `web/server.py` | `tests/web/test_personas_prompts.py` (`liste_des_personas`, `changer_de_persona_change_le_prompt_du_tour`) |  |
| Story 7 Restrictive in the web | ✅ | `web/runtime.py` | `tests/web/test_personas_prompts.py` (`la_persona_retire_write_file_a_l_agent_principal`, `la_persona_s_applique_au_sous_agent`) |  |
