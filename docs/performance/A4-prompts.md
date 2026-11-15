# Real trial - [A4] Prompt Versioning

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `sensai-prompt history` and `check`: ✅ (< 1 s, no model call). Earlier measurements below.

This document records the verification of A4 with a real model, in addition
to the automated tests (`tests/knowledge/test_prompt_versions.py`,
`tests/test_prompt_cli.py`, `tests/test_config.py`,
`tests/test_prompts_registry.py`). Choice:
[ADR-0010](../decisions/0010-prompt-versioning.md).

## What is verified
The Definition of Done: show the history of the system prompts and roll back
to an older version with one command - and above all that **switching version
really changes the agent's behaviour**, and that rolling back restores it.

## Machine and settings
- Team VPS, 8 vCPU, 23 GB RAM, **no GPU**.
- Ollama 0.40.3 installed for the trial in a dedicated folder, without sudo,
  then fully uninstalled (process, folder, `~/.ollama` key, the trial's pip
  cache).
- Model `qwen3:8b` (development model, ADR-0004), preloaded before the first
  question.
- `sensai --no-rag --new-session`: RAG off and a blank session, to isolate
  the prompt's effect.
- A copy of the branch's `prompts/` folder: the trial `v2` never entered the
  repository.

## Scenario
Same question at each launch, asked in English: "What is a Python
decorator? Answer in two sentences."

1. Launch with the shipped version (`system v1`).
2. `sensai-prompt show system > brouillon.txt`, add a line,
   `sensai-prompt save system brouillon.txt "impose le français…"`,
   `sensai-prompt diff system v1 v2`, `sensai-prompt use system v2`.
3. Launch with `system v2`.
4. Rollback: `sensai-prompt use system v1`, then launch.

Difference between v1 and v2, shown by `sensai-prompt diff` (the prompt was
in French at the time; the added line says "Always answer in French, even if
the question is asked in another language"):

```
@@ -9,3 +9,4 @@
 - Si tu ne sais pas, dis-le plutôt que d'inventer.
+- Réponds toujours en français, même si la question est posée dans une autre langue.
```

## Results (2026-10-12)

| Step | Line shown at launch | Answer (start) | Launch duration |
|---|---|---|---|
| 1. v1 | `prompts : system v1, memory v1` | "A Python decorator is a function that wraps another function…" (English) | 150 s |
| 3. v2 | `prompts : system v2, memory v1` | "Un décorateur en Python est une fonction qui enveloppe une autre fonction…" (French) | 101 s |
| 4. back to v1 | `prompts : system v1, memory v1` | "A Python decorator is a function that wraps another function…" (English) | 106 s |

`sensai-prompt history system` after the trial (recorded output):

```
  v2  2026-10-12  Ridwane777        impose le français dans toutes les réponses
  v1  2026-09-22  fresnel-cyber     prompt initial (repris de prompts/system_prompt.txt)  (active)
```

`sensai-prompt check`: "Registry consistent". **The DoD is met**: v2 was not
erased by the rollback, and a single command was enough in each direction.

## Limits
- One scenario, one run per version: the trial shows that the mechanism acts
  on the model, not a success rate.
- The duration includes CLI startup and generation on CPU; it does not
  measure A4, whose commands answer instantly.
- The tested instruction (language) has an easily observed effect; the effect
  of a subtler change needs an evaluation over several questions (EV1),
  planned in the follow-ups of ADR-0010.
