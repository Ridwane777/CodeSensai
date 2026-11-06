# User stories — [R1] Basic RAG

Done when: asking a question about a project file returns an
answer that cites the right passage of the code or the docs.

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

RAG (*Retrieval-Augmented Generation*) gives the agent knowledge the model
was not trained on: the user's files. The full pipeline, as the catalogue
describes it: ingest the local documents, split them, compute their
embeddings, store them in a local vector database, retrieve the passages by
similarity of meaning, and add them to the context sent to the model.

The criteria describe what the user observes; the technical choices (vector
database, embedding model, splitting) are settled in the ADR dedicated to R1.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: where is `maximum` defined: ✅ `stats.py:6` with both models (7 min 41 on CPU, 57 s on GPU, indexing included).

## US-R1-1 — Ask a question about my own code
> **Update on 2026-11-06:** scenario step **S2**, she asks how to run the tests ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who takes over a project she barely knows,
**I want** to ask a question in natural language about the project's code and docs ("where is the login token checked?"),
**so that** I get an answer based on **my** files, not on generalities, without opening the files one by one.

**Acceptance criteria:**
- The answer relies on passages of the project and **cites their source**:
  file path and lines.
- For a question whose answer is in a specific file of the project, the
  cited passage is the right one.
- Questions that are not about the project ("what is a closure in
  Python?") work as before.
- It works on code (`.py`…) **and** on documentation (`.md`).

## US-R1-2 — Index my project without leaks or useless waiting
> **Update on 2026-11-06:** scenario step **S2**, she asks how to run the tests ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who starts CodeSensei on her repository,
**I want** the project to be indexed once, then kept up to date when I edit files,
**so that** the answers reflect the current code, without reindexing the whole project every time.

**Acceptance criteria:**
- A command or an option indexes the project folder and shows how many
  files and passages were indexed.
- After a file is edited, a new indexing only reprocesses the files that
  were modified, added or deleted; a deleted file is never cited again.
- What is useless or sensitive **is never indexed**: `.git`, `.venv`,
  `node_modules`, `__pycache__`, binary files, and above all **`.env` and
  secret files** — any indexed passage can be sent to the model.
- The index is stored locally, outside the repository, like M1's sessions.

## US-R1-3 — Know when the project does not hold the answer
> **Update on 2026-11-06:** scenario step **S2**, she asks how to run the tests ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who trusts the agent's answers to edit her code,
**I want** CodeSensei to tell me when it found nothing relevant in the project,
**so that** I do not receive an invented answer that looks like an explanation of my code.

**Acceptance criteria:**
- For a question about something that does not exist in the project ("where
  is Kafka configured?" in a project without Kafka), the agent says it did
  not find it instead of inventing a file or a function.
- If the project was never indexed, the agent says so and explains how to
  index it, instead of failing silently.
- If Ollama or the embedding model is not available, a clear message is
  shown and the conversation continues without RAG.

## US-R1-4 — Query documents that are not code
> **Update on 2026-11-06:** scenario step **S2**, she asks how to run the tests ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who also works from the client's specification, a project brief and meeting notes,
**I want** to ask questions about these documents ("what are the constraints on frameworks?", "how many user stories per feature?"),
**so that** I find a precise requirement and its source without rereading all the documents, and do not get wrong what is asked.

**Acceptance criteria:**
- I can index a folder of documents that is not a code project
  (notes, specifications, minutes).
- The answer cites the document and the passage the information comes from,
  so that I can check the exact wording.
- The common text formats are supported (Markdown, plain text); support for
  PDF, the usual format of project briefs, is settled in the ADR.
- If the answer is not in the documents, the agent says so (same rule as
  US-R1-3) rather than answering from memory.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-R1-1 | ✅ | `knowledge/rag.py`, `cli.py` | `tests/knowledge/test_rag.py` (`la_bonne_fonction_est_trouvee`, `la_bonne_section_de_doc_est_trouvee`, `le_contexte_cite_fichier_et_lignes`), `tests/test_cli_rag.py::test_premiere_question_indexe_et_cite` |  |
| US-R1-2 | ✅ | `knowledge/rag.py` | `tests/knowledge/test_rag.py` (`env_jamais_indexe_meme_sans_gitignore`, `seuls_les_fichiers_modifies_sont_reindexes`, `fichier_supprime_n_est_plus_cite`, `index_cree_en_prive`) |  |
| US-R1-3 | ✅ | `knowledge/rag.py`, `cli.py` | `tests/knowledge/test_rag.py` (`sous_le_seuil_rien_n_est_renvoye`, `contexte_vide_previent_le_modele`), `tests/test_cli_rag.py::test_ollama_indisponible_la_conversation_continue` | Not inventing remains model behaviour |
| US-R1-4 | ✅ | `knowledge/documents.py`, `knowledge/rag.py` | `tests/knowledge/test_rag_documents.py` |  |
