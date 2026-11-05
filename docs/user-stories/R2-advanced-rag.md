# User stories — [R2] Advanced RAG

Issue #56, high priority.

Catalogue: extend R1 with re-ranking of the retrieved passages, metadata
filtering, and a relevance score per passage to discard near-matches before
they enter the context. Depends on R1 ([R1-basic-rag.md](R1-basic-rag.md),
[ADR-0009](../decisions/0009-rag-sur-la-codebase.md)).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

**Baseline to beat** (R1, [measurements](../performance/R1-rag.md)): on 15
questions in French about the repository, the right file comes first
11 times out of 15; the 0.50 threshold discards the 3 questions whose answer
is not in the repository.

The technical choices (re-ranking method, metadata, score computation and
threshold) are settled in the ADR dedicated to R2.

---

## US-R2-1 — The passage that really answers, first

**As** Camille, the developer asking a precise question about her code,
**I want** the search to re-rank the passages found so that the one that really answers the question comes first,
**so that** the model relies on the right file and cites it.

**Acceptance criteria:**
- On R1's set of 15 questions, the right file comes first more often than
  with R1 (11/15), measured by a script.
- The time added per question is measured and shown in the report.
- If re-ranking fails (missing model, error), R1's order is kept without
  crashing.

## US-R2-2 — Search only where needed

**As** Camille, the developer who knows where the answer is,
**I want** to limit a search to one part of the project (the docs, the code, the tests, a folder),
**so that** I do not receive off-topic passages.

**Acceptance criteria:**
- The agent can filter `search_codebase` by type (code, documentation,
  tests) or by folder.
- A passage outside the filter is never returned.
- An unknown filter gives a clear message instead of an empty result.

## US-R2-3 — Discard the passages that look alike without answering

**As** Camille, the developer who relies on the cited passages,
**I want** each passage to have a relevance score, and the weakest to be discarded before reaching the model,
**so that** the model does not rely on a passage that looks like the question without answering it.

**Acceptance criteria:**
- Each passage sent to the model carries its relevance score.
- Below a threshold set by measurement, the passage is discarded.
- The 3 questions with no answer in the repository (Kafka, Stripe, e-mails)
  still receive no passage.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-R2-1 | ✅ | `knowledge/retrieval.py`, `scripts/bench_rerank.py` | `tests/knowledge/test_retrieval.py` (`le_modele_reordonne_les_premiers`, `reclassement_rate_garde_l_ordre_de_la_fusion`) | The 15-question comparison is a script measurement ([R2-rag.md](../performance/R2-rag.md)), not a test |
| US-R2-2 | ✅ | `knowledge/retrieval.py`, `tools/rag_tool.py` | `tests/knowledge/test_retrieval.py` (`filtre_code`, `filtre_doc`, `filtre_dossier`), `tests/tools/test_rag_tool.py` |  |
| US-R2-3 | ✅ | `knowledge/retrieval.py` | `tests/knowledge/test_retrieval.py` (`chaque_passage_garde_son_score_de_similarite`, `le_seuil_s_applique_aussi_aux_passages_de_bm25`) |  |
