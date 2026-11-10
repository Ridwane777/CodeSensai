# User stories — [M3] External Structured Memory

Issue #57, mandatory since ADR-0008
(scope: the 28 features).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)).

Catalogue: memory moves into a real database (SQLite/NoSQL). The agent itself
reads, writes and updates structured records (facts, entities, relations)
through CRUD operations, over time. The operations are exposed as tools by
the tool registry and the gateway.

**Difference with M1 and M4**:
- M1 keeps the raw conversation (sessions, 30 days) and the profile, which
  the user fills in herself with `/remember`;
- M4 (`SENSAI.md`) is a prose report of progress, meant to be read by a
  human;
- M3 keeps **precise, organised facts**, which the agent creates, corrects
  and retrieves itself, with no time limit: it answers "what do we know about
  this element?".

The criteria describe what the user observes; the technical choices (data
model, tools, confirmation, search) are settled in the ADR dedicated to M3.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `/remember` then `/profile`: ✅ with both set-ups (< 1 s).

## US-M3-1 — The agent remembers a fact without being told again
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who explains her project over the sessions,
**I want** the agent to record the important facts by itself (an entity, what characterises it, its links with others),
**so that** I do not have to repeat them in every session.

**Acceptance criteria:**
- When I say "the auth service uses Redis 7", the agent records a
  structured fact (entity `auth`, attribute, value), after confirmation.
- The fact is kept after the CLI is closed, in a local database.
- A fact that already exists is not created twice: it is updated.

## US-M3-2 — The agent finds the facts useful to answer
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who asks a question weeks later,
**I want** the agent to search its structured memory before answering,
**so that** I get an answer that takes into account what I taught it.

**Acceptance criteria:**
- To "which version of Redis does auth use?", the agent looks up its memory
  and answers "7", citing the fact.
- It can list everything it knows about an entity, and the entities linked
  to another ("what depends on Redis?").
- If it knows nothing, it says so instead of inventing.

## US-M3-3 — Correct or forget a fact
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose project changes,
**I want** the agent to update a fact that has become wrong, and to be able to delete one,
**so that** I keep an accurate memory.

**Acceptance criteria:**
- "We moved to Redis 8" updates the existing fact, and the old value stays
  visible in the history.
- I can list, view and delete facts without going through the model (a
  command in the chat).
- The memory is specific to each project: one project's facts do not appear
  in another.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-M3-1 | ✅ | `knowledge/facts.py`, `tools/fact_tools.py` | `tests/tools/test_fact_tools.py::test_save_asks_confirmation_and_a_refusal_saves_nothing`, `tests/knowledge/test_facts.py` (`un_fait_survit_a_une_nouvelle_instance`, `pas_de_doublon_noms_compares_sans_casse_ni_espaces`) | Duplicates under two entity names still happen ([backlog](../backlog.md) #12) |
| US-M3-2 | ✅ | `tools/fact_tools.py` | `tests/tools/test_fact_tools.py` (`retenir_puis_retrouver_par_les_outils`, `rien_trouve_le_dit`), `tests/knowledge/test_facts.py::test_inverse_relations` |  |
| US-M3-3 | ✅ | `knowledge/facts.py`, `/facts` | `tests/knowledge/test_facts.py` (`l_ancienne_valeur_reste_dans_l_historique`, `oublier_un_fait_precis`, `la_memoire_est_propre_au_projet`), `tests/test_cli_rag.py::test_commande_facts` |  |
