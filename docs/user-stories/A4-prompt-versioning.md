# User stories - [A4] Prompt Versioning

Registry and command `sensai-prompt`; web page (US-A4-4, US-A4-5). Mandatory
since ADR-0008 (scope: the 28 features).

Done when: the history of the system prompts can be shown and an older
version restored in one command.

**For whom:** Marc, the lead who adjusts the agent's prompts for his team
(ReAct, guardrails, persona) and needs them versioned, comparable and
rollback-able. Feature A7 (Automated Prompt Optimization) builds on it.

The criteria describe what Marc and Camille observe; the technical choices (storage,
version identifiers, commands) are decided in the A4 ADR
([ADR-0010](../decisions/0010-prompt-versioning.md)).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `sensai-prompt history` and `check`: ✅ with both set-ups (< 1 s).

## US-A4-1 - Find what changed in a prompt, and when
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who notices the agent has answered differently for a few days,
**I want** to see the list of a prompt's versions with their date, and compare two versions,
**so that** I find which change altered the behaviour, without digging through git history.

**Acceptance criteria:**
- A command shows a prompt's versions, from the most recent to the oldest,
  with their date.
- A command shows the differences between two versions, line by line.
- A saved version is never modified.

*Real case: the M1 memory prompt (`prompts/memory_prompt.txt`), added after
the trials, changed the model's answers ("I have no memory" became "yes, you
had a login bug") - see
[docs/performance/M1-sessions.md](../performance/M1-sessions.md).*

## US-A4-2 - Save a new version effortlessly
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who edits a prompt (for example the ReAct prompt),
**I want** my change to become a new dated version, with a short description,
**so that** the history stays complete without my having to think about it.

**Acceptance criteria:**
- Each change to a prompt creates a new version, with its date.
- A short description can be attached ("add the memory instruction").
- A change that does not alter the text creates no version.

## US-A4-3 - Go back in one command
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who notices that a new version degrades the answers,
**I want** to go back to a previous version in a single command,
**so that** I restore a behaviour that worked, without touching the code.

**Acceptance criteria:**
- A command makes a previous version active; the next `sensai` runs use it.
- Going back deletes no version: one can then return to the most recent.
- This is the Definition of Done: show the history and go back to an older
  version in one command.

## US-A4-4 - Browse the real registry from the web interface
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

*Update on 2026-11-01 (
[ADR-0055](../decisions/0055-prompt-versions-in-the-web.md)): ◐ tested with
pytest and vitest, not yet with the real model.*

**As** Marc, the lead using `sensai-web`,
**I want** the Prompts page to show the real registry (versions, author, date,
description, active one), the text of a version and a diff between two versions,
**so that** I can follow the prompts without a terminal.

**Acceptance criteria:**
- With the real server, the page lists the prompts of `prompts/versions.json`
  and their versions, the active one marked; no demo version is shown.
- Selecting a version shows its text; choosing a second version shows a
  unified diff.
- Nothing on the page can save a version or change the active one: the
  registry files keep the same bytes (checked by a test).

## US-A4-5 - Try a system prompt version in one conversation
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

*Update on 2026-11-01: ◐ tested with a scripted model (pytest) and vitest,
not yet with the real model.*

**As** Marc, the lead hesitating between two versions of the system prompt,
**I want** to try a version in the conversation I have open, and go back,
**so that** I compare its effect on a real question without changing the
prompt for the rest of the team.

**Acceptance criteria:**
- "Essayer dans cette conversation" makes the next turns of that conversation
  (and its sub-agents) use that version's text; other conversations keep the
  normal prompt.
- A badge "prompt system vN (essai)" is shown in the chat, with a way back to
  the active version.
- An unknown version is refused (404); the version cannot be changed while a
  turn runs (409).
- The trial is held by the server while it runs, not saved; activating a
  version for everyone stays `sensai-prompt use`.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-A4-1 | ✅ | `knowledge/prompt_versions.py`, `prompt_cli.py` | `tests/knowledge/test_prompt_versions.py` (`historique_du_plus_recent_au_plus_ancien`, `diff_entre_deux_versions`, `version_modifiee_detectee`) |  |
| US-A4-2 | ✅ | `prompt_cli.py` (`save`) | `tests/test_prompt_cli.py` (`save_depuis_un_fichier`, `save_d_un_texte_identique_refuse`) | A version is created by `sensai-prompt save`, not automatically when the file is edited |
| US-A4-3 | ✅ | `prompt_cli.py` (`use`) | `tests/test_prompt_cli.py::test_dod_history_then_rollback`, `tests/knowledge/test_prompt_versions.py::test_rollback_loses_nothing` |  |
| US-A4-4 | ✅ | `web/server.py`, `frontend/src/pages/Prompts.tsx` | `tests/web/test_personas_prompts.py` (`liste_du_registre`, `texte_et_diff_d_une_version`, `le_web_n_ecrit_jamais_le_registre`), `frontend/tests/personasPrompts.test.tsx` |  |
| US-A4-5 | ✅ | `web/runtime.py` | `tests/web/test_personas_prompts.py` (`essai_d_une_version_dans_une_conversation`, `essai_version_inconnue_ou_pendant_un_tour`) |  |
