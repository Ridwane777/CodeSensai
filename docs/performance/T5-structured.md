# T5 - Structured output: is the answer grounded in the project?

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `/structured` on the project: qwen3-coder:30b on GPU ✅ 3 of 3 with RAG on after the index fix, ✅ 3 of 3 with RAG off after `list_files` (10–24 s); qwen3:8b on CPU ❌ (calls no tool, names one of its own MCP tools). Earlier measurements below.

Measurements of 2026-10-24 on the RunPod pod (GPU, Ollama), model
`qwen3-coder:30b`, Linux client (Python 3.12). Decisions:
[ADR-0036](../decisions/0036-structured-output-json-schema-format.md) and
[ADR-0039](../decisions/0039-project-grounded-structured-output.md).
All figures are measured; the sample is small (5 runs per question).

## Reproduce

    python scripts/bench_t5.py <Ollama host> [runs]

The script creates a throwaway project (`stats.py`, `texte.py`, `reglages.py`)
and asks three questions with known answers. "Correct": the expected function
names (signature ignored) or the right port value.

## Results (5 runs per question)

| Question | Direct call (ADR-0036) | Two-step (ADR-0039) |
| --- | --- | --- |
| Functions in `stats.py` (only one: `maximum`) | 0/5 - invented (`mean`, `median`, `mode`…) | 5/5 |
| Functions in `texte.py` (`compter_mots`, `inverser`) | 0/5 - invented | 5/5 |
| Port in `reglages.py` (8042) | 0/5 - 5000, 8080… | 5/5 |
| **Total** | **0/15**, 0.9 to 3.9 s | **15/15**, 3.7 to 15.8 s |

## Tuning found along the way

First two-step pass: 5 out of 9, then 8 out of 9 once the check was fixed (it
rejected `inverser(phrase)` instead of `inverser`). The last failure came from
the formatting step: the agent had found both functions, but the JSON
returned an empty list. The instruction "leave a field empty only if the
information really isn't there" fixed it: 15 out of 15 afterwards.

## Limits

- Three simple questions on a small project; a single model.
- The formatting step copies the agent's answer: an agent error ends up in
  the JSON.
- Names keep the form the agent wrote (with or without signature).
