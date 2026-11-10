# User stories — [M4] Artifact & State Document

Issue #39, mandatory since ADR-0008 (scope: all
28 features). Translated from French on 2026-10-29.

Catalogue: the agent maintains a **living document** (project changelog,
up-to-date spec) separate from the raw history. The model must be able to
change one specific section without rewriting the whole document, with an
edit format the agent can parse.

Definition of Done: after several exchanges, the document reflects the state
of the project without being corrupted or fully rewritten at each turn.

**Difference with M1**: M1 keeps the raw conversation, to resume it. M4 keeps
a **summary** that the agent keeps up to date and that can be read without
the conversation.

The criteria describe what the user observes; the technical choices (file
location, edit format, confirmation) are settled in the ADR dedicated to M4.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `/state`: ✅ with both set-ups (< 1 s).

## US-M4-1 — Know where the project stands when coming back to it
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer coming back to her project after several days,
**I want** a state document kept up to date by the agent (what is done, what is in progress, the decisions taken, the known problems),
**so that** I know where things stand without rereading every conversation.

**Acceptance criteria:**
- The document is a file that can be read and edited by hand, stored in the
  project and organised in named sections.
- At the start of each session, the agent knows its content: it can answer
  "where are we?" without rereading it.
- If the file does not exist, the agent creates it with the base sections at
  the first update.

## US-M4-2 — A targeted update, never a destructive one
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who wrote part of the document myself,
**I want** the agent to change only the section concerned,
**so that** I never lose what I wrote in the other sections.

**Acceptance criteria:**
- After an update of "En cours", every other section stays byte-for-byte
  identical.
- An update aimed at a section that does not exist, or that is malformed, is
  refused with a clear message, and the file stays intact.
- An interrupted write (crash, Ctrl+C) never leaves a half-written file.

## US-M4-3 — See and control what the agent changes
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who lets the agent maintain the document,
**I want** to see each change and be able to go back,
**so that** I keep trusting what it writes.

**Acceptance criteria:**
- Each update shows the section before and after (a diff).
- Each change leaves a trace: date, section, summary.
- The last change of a section can be undone.

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): the Artefact panel is filled at load from `GET /api/state` (`bodies`, one entry per section), and each section changed by an `update_state` call is pushed live as an `artifact_patch` event. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): `update_state` sent an `artifact_patch`, `GET /api/state` returned the section, and the Artefact panel showed the real `SENSAI.md`.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-M4-1 | ✅ | `knowledge/state_document.py` | `tests/knowledge/test_state_document.py::test_first_update_creates_default_sections`, `tests/test_cli_rag.py::test_le_document_d_etat_est_dans_le_prompt_systeme` |  |
| US-M4-2 | ✅ | `knowledge/state_document.py` | `tests/knowledge/test_state_document.py` (`les_autres_sections_restent_identiques_a_l_octet`, `section_inconnue_refusee_avec_la_liste_et_fichier_intact`, `ecriture_interrompue_ne_laisse_pas_un_fichier_a_moitie_ecrit`) |  |
| US-M4-3 | ✅ | `knowledge/state_document.py`, `tools/state_tool.py` | `tests/tools/test_state_tool.py::test_confirmation_shows_before_and_after`, `tests/knowledge/test_state_document.py` (`chaque_mise_a_jour_est_journalisee`, `annuler_remet_la_section_dans_son_etat_precedent`) | The model may say it updated the document without calling the tool ([backlog](../backlog.md) #17) |
