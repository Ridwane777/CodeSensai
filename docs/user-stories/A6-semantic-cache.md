# A6 — Semantic cache: user stories

Catalogue feature: **[A6] Semantic Cache (★★)**. Cache the answers and serve
them directly for questions that are close in meaning (embedding comparison),
without calling the model. Issue #58.

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)).

What is done elsewhere (Redis LangCache, GPTCache, LiteLLM): the cache mostly
serves information questions asked in a single turn and often rephrased (FAQ,
internal Q&A, RAG). Agent loops and multi-turn conversations are excluded.
The main risk is the false positive: two questions close in meaning that call
for different answers. Hence the use case chosen here, the "repository FAQ".

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: cache on, same question twice: qwen3:8b ✅ (5 min 37, then 0.5 s); qwen3-coder:30b ✅ (9.0 s, then 1.8 s). Identical question only, not a rephrasing.

## US-A6-1 — The project FAQ
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** the cache is **off by default** since 2026-11-02 ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 5). It is turned on with `"cache": true` in `config.json` or `sensai --cache`; without it, every question goes to the model. The criteria below apply once it is on.

**As** Camille, the developer arriving on a project,
**I want** an immediate answer to the questions everybody asks
("how do I run the tests?", "where is the database config?"), even
phrased differently,
**so that** I do not wait for the model on a question already handled.

Acceptance criteria:
- A rephrasing of a question already asked gets its answer in less than one
  second, without a call to the chat model, measured by a script of the repository.
- The rate of answers served from the cache is measured on a set of
  realistic questions and documented.

## US-A6-2 — Not be fooled
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** the cache is **off by default** since 2026-11-02 ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 5). It is turned on with `"cache": true` in `config.json` or `sensai --cache`; without it, every question goes to the model. The criteria below apply once it is on.

**As** Camille, the developer who relies on the answers to edit the code,
**I want** the cache to refuse to answer as soon as there is a doubt,
**so that** I never receive the answer to another question, nor the
description of code that has changed since.

Acceptance criteria:
- On a set of trap pairs written before any measurement ("add" and
  "delete", "read" and "write a file"…), none is served from the cache.
  The similarity threshold is chosen from this measurement.
- An entry is invalidated as soon as a project file the answer relied on is
  modified or deleted.
- A turn in which the agent wrote a file or ran code is never cached, nor is
  a question that depends on the current conversation.

## US-A6-3 — Know and decide
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
>
> **Update on 2026-11-06:** the cache is **off by default** since 2026-11-02 ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 5). It is turned on with `"cache": true` in `config.json` or `sensai --cache`; without it, every question goes to the model. The criteria below apply once it is on.

**As** Camille, the developer,
**I want** to see that an answer comes from the cache and be able to refuse it,
**so that** I stay in control of what I believe.

Acceptance criteria:
- An answer served from the cache carries the mention "depuis le cache",
  with the original question and its date.
- One command asks the model for the answer again, another empties the cache.
- `/cache` shows the number of entries, the number of answers served and the
  time saved.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-A6-1 | ✅ | `knowledge/cache.py`, `cli.py`, `scripts/bench_cache.py` | `tests/test_cli_cache.py::test_a_repeated_question_does_not_call_the_model_again`, `tests/knowledge/test_cache.py::test_the_same_question_is_served` | Timing and hit rate are measured by the script, not by a test |
| US-A6-2 | ✅ | `knowledge/cache.py`, `cli.py` (`CACHEABLE_TOOLS`) | `tests/knowledge/test_cache.py` (`une_action_differente_n_est_jamais_servie`, `un_fichier_modifie_invalide_la_reponse`, `un_fichier_supprime_invalide_la_reponse`, `une_question_dependante_n_est_ni_servie_ni_enregistree`) |  |
| US-A6-3 | ✅ | `ui.py` (`cached_answer`), `cli.py` (`/again`, `/cache`) | `tests/test_cli_cache.py` (`again_redemande_au_modele`, `commande_cache`), `tests/knowledge/test_cache.py::test_clear_the_cache` |  |
