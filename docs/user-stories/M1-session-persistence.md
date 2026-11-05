# User stories — [M1] Session persistence & profiles

CodeSensei scenario: Camille, working alone or with Marc's small team, on a long
project. What she loses each time the CLI restarts — the conversation context
and her working habits — is what M1 must give back.

The acceptance criteria describe what the user observes, not how it is done:
the storage and the location of the data are settled in the ADR dedicated to
M1.

---

## US-M1-1 — Pick up where I left off

**As** Camille, the developer who works on the same project over several days,
**I want** to find my previous conversation with CodeSensei when I restart the CLI,
**so that** I do not have to re-explain the context (the current bug, the files involved, what we already tried).

**Acceptance criteria:**
- After quitting the CLI (`exit`, Ctrl+C or Ctrl+D) and restarting it, the
  agent answers a question that refers to an exchange from the previous
  session ("tu te souviens du bug dont on parlait ?").
- At startup, the CLI says that a session is resumed and how many messages it
  contains.
- If a model response fails (Ollama unavailable, network outage), the failed
  message is not saved: on resume, the history does not contain a half
  exchange.
- The history is kept on the user's machine, outside the code repository, and
  cannot be committed by mistake.

## US-M1-2 — Not repeat my preferences

**As** Camille, the developer with her own habits (Python 3.12, pytest, answers in French, no unnecessary dependency),
**I want** CodeSensei to know my preferences and instructions from startup, without me repeating them,
**so that** every answer follows my way of working from the start, even in a new conversation.

**Acceptance criteria:**
- I can add, show and clear my preferences without changing the code.
- An added preference is still there after closing and restarting the CLI.
- In a **new** session, without any reminder from me, the answer follows a
  saved preference (with "utilise pytest", a generated test uses pytest, not
  unittest).
- If the profile file is missing or unreadable, the CLI still starts, with an
  empty profile and a warning — it does not crash.

## US-M1-3 — Choose which conversation to resume

**As** Camille, the developer who handles several topics in parallel (an authentication bug, an API redesign),
**I want** to list my past conversations and choose the one to resume, or start a new one,
**so that** the contexts of different topics do not get mixed.

**Acceptance criteria:**
- I can show the list of my sessions, each with a readable title, the date of
  last change and the number of messages.
- I can resume a specific session by its identifier, or start a blank
  session.
- A new session contains no message from the others, but keeps my profile
  (US-M1-2).
- Sessions are accessible from the Python code, not only from the CLI, so
  that the web interface can reopen them (`GET /api/sessions` in the API
  contract).
- In the web interface, the Memory page lists the conversations of the project (title, message count, last change) and "Rouvrir" opens one in the chat: its history is shown and the next message continues it. Checked on 2026-10-29 in a headless Chromium against a local `sensai-web` with two saved conversations, twice with the browser closed in between (list shown, conversation reopened, history visible). Continuing the reopened conversation is covered by the frontend tests (`frontend/tests/httpEngine.test.ts`), not yet tried with the real model.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-M1-1 | ✅ | `knowledge/memory.py` (`SessionStore`, SQLite) | `tests/test_cli_persistence.py` (`historique_conserve_apres_relance`, `tour_en_echec_non_sauvegarde`), `tests/knowledge/test_memory.py::test_dossier_cree_en_700_et_base_en_600` | Recalling the earlier exchange in words depends on the model |
| US-M1-2 | ✅ | `knowledge/memory.py` (`Profile`), `/remember`, `/profile`, `/forget` | `tests/test_cli_persistence.py` (`preference_conservee_apres_relance`, `profil_illisible_ne_bloque_pas_le_demarrage`), `tests/knowledge/test_memory.py::test_profil_injecte_dans_le_prompt_systeme` | Following the preference in the answer depends on the model ([backlog](../backlog.md) #11) |
| US-M1-3 | ✅ | `knowledge/memory.py`, `web/server.py` (`/api/sessions`) | `tests/knowledge/test_memory.py` (`liste_des_sessions_du_projet`, `reprendre_une_session_precise`, `nouvelle_session_ignore_l_historique`), `tests/web/test_server.py` |  |
