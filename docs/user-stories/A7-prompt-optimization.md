# A7 — Automated Prompt Optimization

See [ADR-0044](../decisions/0044-automatic-few-shot.md) for the design
(semantic few-shot selection, reusing the EV1 dataset format and the R1
embedder).

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: few-shot example `pytest -q`: ✅ with both models (6 min 03 on CPU, 16 s on GPU).

## User Story 1: Writing a few-shot library without inventing a new format
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensei up ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Marc, the lead improving the agent's answers on a recurring kind of
question**, I want to **write a library of good examples (question +
answer) in the same format I already use for evaluation**, so that **I
don't have to learn or maintain a second file format just for this
feature**.

### Acceptance criteria

- `fewshot_examples` in `config.json` (or `--fewshot-examples`) points to a
  JSONL file in the EV1 dataset format (`eval/dataset.py`): `id`,
  `question`, `answer` per line.
- A case without an `answer` is silently unusable as an example (it's a
  normal EV1 case without one — not an error, since the same file could
  also be used for `sensai-eval`).
- A missing, unreadable, or malformed file disables the feature with a
  clear warning at startup; it never stops the CLI from working otherwise.

## User Story 2: Getting a relevant example without asking for one
> **Update on 2026-11-06:** scenario step **S2**, she asks how to run the tests ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer asking a question close to one already answered well before**,
I want **the agent to see that earlier example automatically**, so that
**my answer follows the same style and level of detail, without me having
to paste the example myself every time**.

### Acceptance criteria

- Before a question reaches the model, if a configured example's question
  is semantically close enough (`fewshot_min_score`, default 0.75 — an
  estimate, see ADR-0044), it is
  attached to the question sent to the model — never to the system prompt,
  and never saved into the session's history.
- A question with no sufficiently close example reaches the model
  unchanged: nothing is added "just in case".
- The attached example is clearly marked as an example to draw inspiration
  from, not a question to answer — the real question is still the one
  being asked.

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): few-shot now works in `sensai-web` as in the CLI (`fewshot_examples`, `fewshot_min_score`, example attached to the question, `fewshot` event); a missing or broken examples file becomes a notice instead of an error. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): in `sensai-web`, the few-shot example was attached to the first question; a French example once overrode an English language preference (finding 3).

> **Update on 2026-11-01 (branch `feat/fewshot-visible`):** ✅ In `sensai-web`, the Prompts page shows the real examples (file, threshold, questions, `GET /api/fewshot`) instead of simulated variants, and the chat shows « Inspirée de l'exemple : … » under an answer that got one. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| Story 1 Example library | ✅ | `knowledge/fewshot.py` | `tests/knowledge/test_fewshot.py` (`charge_seulement_les_cas_avec_une_reponse`, `fichier_mal_forme_leve_fewshoterror`), `tests/test_cli_fewshot.py::test_fichier_introuvable_n_empeche_pas_la_conversation` |  |
| Story 2 Relevant example | ✅ | `knowledge/fewshot.py`, `cli.py`, `web/runtime.py` | `tests/test_cli_fewshot.py` (`question_proche_recoit_lexemple`, `question_sans_rapport_ne_recoit_rien`), `tests/knowledge/test_fewshot.py::test_format_example_contient_question_et_reponse_sans_repondre_a_sa_place` |  |
