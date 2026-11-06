# User stories — [T5] Structured Output

Decision: [ADR-0036](../decisions/0036-sortie-structuree-format-json-schema.md).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)), who wants
the agent to return a result that a script can read directly (for example to
feed it into another tool), without extracting the information from free text.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `/structured` on the project: ❌ with both models, schema respected but content wrong (qwen3:8b) or vague (qwen3-coder:30b); with RAG off the agent did not find `stats.py` (backlog #25).

## US-T5-1 — Get an answer that follows a given schema
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who will consume the answer in a script,
**I want** to ask for a JSON answer that matches a schema I provide,
**so that** I can read it directly without parsing free text or
guessing where each field is.

**Acceptance criteria:**
- `/structured schema.json "liste les fichiers Python du dossier courant"`
  with a schema `{"type": "object", "properties": {"files": {"type":
  "array", "items": {"type": "string"}}}, "required": ["files"]}` returns a
  JSON object that does have a `files` key holding a list of strings.
- The answer shown in the chat is the formatted (indented) JSON, not
  a prose description of the JSON.

## US-T5-2 — Be clearly warned when the constraint cannot be met
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who uses `/structured` in a script,
**I want** an explicit error message if the schema is unreadable or if
the model did not produce valid JSON,
**so that** I know I cannot trust the answer, rather than
receiving a truncated object without knowing it.

**Acceptance criteria:**
- `/structured fichier-absent.json "..."` shows a message that names the
  missing file, without crashing the chat or sending a request to Ollama.
- `/structured schema-invalide.json "..."` (malformed JSON) shows a
  schema reading error, not a Python trace.
- If Ollama still returns text that is not valid JSON (for example an
  Ollama version too old that ignores `format`), the chat shows an error
  naming the start of the answer received rather than presenting it as a
  structured result.

## US-T5-3 — A structured answer about the real project
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who asks for a JSON about her code,
**I want** the answer to rely on the project's files,
**so that** I do not receive a well-formed but invented JSON.

**Acceptance criteria:**
- `/structured schema.json "liste les fonctions de stats.py"` first has the
  agent read the file (the tool call is shown), then returns
  only the functions defined in it.
- If the agent cannot search (Ollama unavailable), the chat shows a
  clear error and no invented JSON.

> **Status on 2026-10-24:** ✅ Checked on the pod: 15 right answers out of 15
> in two steps, against 0 out of 15 with the direct call
> ([T5-structured.md](../performance/T5-structured.md)). Search failure:
> covered by the tests.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-T5-1 | ✅ | `core/structured.py` | `tests/core/test_structured.py` (`passe_le_schema_dans_le_champ_format`, `renvoie_le_json_parse`) |  |
| US-T5-2 | ✅ | `core/structured.py` | `tests/core/test_structured.py` (`json_invalide_leve_une_erreur_explicite`, `schema_mal_forme_est_signale`) |  |
| US-T5-3 | ✅ | `core/structured.py` | `tests/core/test_structured.py::test_avec_gather_la_reponse_de_l_agent_sert_de_source`, `tests/test_cli_rag.py::test_structured_s_appuie_sur_ce_que_l_agent_a_trouve` | A wrong judgement was seen once with the real model ([backlog](../backlog.md) #16) |
