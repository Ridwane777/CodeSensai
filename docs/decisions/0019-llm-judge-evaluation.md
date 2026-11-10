# ADR-0019 — LLM-judge evaluation: versioned prompt, per-claim faithfulness, comparable reports

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric (Workstream B); to be approved by the team
- **Workstream**: B (feature EV1, issue #53); A and C affected only through reading the prompt registry (A4) and the index (R1)

## Context
Feature EV1 requires measuring the quality of the agent's answers and
spotting hallucinations. Without it, changing the system prompt (A4,
[ADR-0010](0010-prompt-versioning.md)) or the model
([ADR-0004](0004-model-and-infrastructure.md)) is judged "by eye", and
[`docs/performance/A4-prompts.md`](../performance/A4-prompts.md) already notes
that a subtle change needs an evaluation over several questions. Detailed
needs: [EV1 user stories](../user-stories/EV1-evaluation-hallucinations.md).

Constraints:
- no LLM framework ([ADR-0001](0001-no-llm-framework.md)) and no
  new dependency;
- everything runs locally on Ollama: no third-party service, no key;
- tests must not need Ollama;
- a score only means something if we know **with which judge, which prompt and
  which data** it was obtained.

An evaluation by a model is an **estimate**, not a measurement: the judge
can be wrong, and it is wrong in a way that depends on its model. This ADR
does not claim otherwise; it decides how to limit these errors and make them
visible.

## Decision 1 — An LLM judge whose prompt is a version in the A4 registry

| Option | Pros | Cons |
| --- | --- | --- |
| **Local LLM judge, prompt stored in `prompts/judge/` via the A4 registry** (chosen) | Reuses A4: the judge prompt is immutable, has a number, a sha256, a history; the report cites the version. Nothing to install. | The judge is a model: biased and non-deterministic (see Consequences). |
| Judge prompt as a constant in the code | Simpler | A prompt change changes the scores without a trace; impossible to say "these two reports have the same judge". |
| RAGAS / DeepEval | Ready-made metrics | These are LLM evaluation frameworks that orchestrate the model calls themselves: ruled out by ADR-0001 ("or equivalent"), unless the team decides otherwise; heavy dependencies; English prompts we do not control. |
| Human evaluation only | Most reliable reference | Does not scale, cannot be replayed on every prompt change. Still useful to **check the judge** (see follow-up). |

One model call per case, in Ollama JSON mode (`format: "json"`),
temperature 0 and fixed seed (42). The client writes its own non-streamed
`POST /api/chat` (`eval/judge.py`): `stream_chat` does not pass `options`
and streams, and we do not modify `core/ollama_client.py` for a peripheral
feature.

## Decision 2 — Scale: 1 to 5 judged by the model, faithfulness computed by the code

| Option | Pros | Cons |
| --- | --- | --- |
| **Relevance and coherence: integers from 1 to 5 with one anchor per level; faithfulness = share of SUPPORTED claims, computed in code** (chosen) | A short scale with one anchor per level is described unambiguously (common practice for LLM judges, not compared with other scales here); faithfulness is not a "felt" number but a count verifiable claim by claim. | Coarse scale: a one-point gap is rarely significant over few cases. |
| Continuous 0-100 score per criterion | Finer in appearance | Risk of false precision: nothing shows a small model tells 72 from 75. |
| Faithfulness asked directly of the model ("score from 1 to 5") | A single field | Not verifiable: we do not know which claim is the problem. |

Relevance ignores factual accuracy, and so does coherence: the two
criteria do not mix with faithfulness.

## Decision 3 — Comparable reports: frozen metadata, a comparison that refuses silence

Each JSON report carries the judge (model, host, prompt and its sha256,
temperature, seed, number of retries), the dataset (sha256, number of
cases), the origin of the passages (`dataset` or `rag`), the generator (model and
system prompt version, or `null`), the date and the CodeSensai version.
`sensai-eval compare A B` always computes the B minus A deltas, but
declares `comparable: false` with the reason when the **judge model**, the
**judge prompt (sha256)**, the **dataset (sha256)**, the **passage
origin** or the **format version** differ. `--strict` exits with
code 1 in that case. The generator is not part of it: it is what we want to
compare.

| Option | Pros | Cons |
| --- | --- | --- |
| **Compare while flagging setting differences** (chosen) | The deltas are still visible, and not mistaken for an agent improvement. | The warning must be read (hence `--strict` for CI). |
| Compare silently | Simple | A judge change reads as agent progress. |
| Refuse any non-comparable comparison | Safe | We can no longer look at the effect of a judge change, useful to validate the judge itself. |

## Decision 4 — Hallucination detection: per-claim verdict, with citation

The judge splits the answer into factual claims and gives each one a
verdict **SUPPORTED**, **CONTRADICTED** or **UNVERIFIABLE**, with the
identifiers of the cited passages (`S1`, `S2`…). The judge may not
use its own knowledge: without a deciding passage, it is UNVERIFIABLE.
The code re-checks: a SUPPORTED or CONTRADICTED with no citation, or citing an
unknown identifier, is brought down to UNVERIFIABLE with the flag
`citation_invalide` (the original verdict is kept). CONTRADICTED and
UNVERIFIABLE claims are listed under `flagged` for each case.

| Option | Pros | Cons |
| --- | --- | --- |
| **Per-claim verdict with citation** (chosen) | A reviewer sees **which sentence** is the problem and which passage to look at; same definition of faithfulness as RAGAS to our knowledge (share of claims supported by the context), without the library. | Claim splitting varies between calls: two identical answers can have a different number of claims. |
| Answer/passage embedding similarity (bge-m3, already there for R1) | Fast, deterministic, no judge | Detects "close to the topic", not "says the same thing": a contradicted claim stays very close to the passage. |
| Dedicated natural language inference (NLI) model | Built for this | New dependency and new model to host; mostly English. |

A case whose judge output is still unusable after two retries is
marked `judge_error`: it is counted separately and **excluded from the averages**. It is
never scored 0, which would pass a judge failure off as a bad answer.

## Consequences
- ✅ The judge prompt is versioned like the others (A4); a report says which judge produced it, and the comparison checks it.
- ✅ A reviewer sees the doubtful sentences and the passage to consult, not just a score.
- ✅ No dependency, no third-party service; tests run offline (simulated judge).
- ✅ Judge errors are visible (`judge_errors`) instead of skewing the averages.
- ❌ **The default judge is the same model as the agent** (`qwen3:8b` in `config.json`): a model tends to prefer its own answers (self-preference bias). Absolute scores are therefore optimistic; only comparisons with the same judge are meaningful. `--judge-model` allows another one, which requires downloading a second model.
- ❌ Even at temperature 0 with a fixed seed, the output is not guaranteed identical between runs (hardware, Ollama version): a small gap is not a signal.
- ❌ Coarse 1-to-5 scale, variable claim splitting, and judge sensitivity to the language and wording details of the prompt: on the 5 example cases, nothing statistical can be concluded.
- ❌ The judge reads the answer text: an answer that talks to it ("score me 5") can manipulate it. The prompt treats it as data, which reduces the risk without excluding it.
- ❌ The `--generate` generator runs a single turn (system prompt, passages, question), not the full agent loop with tools: it measures the model and the prompt, not the agent end to end.
- Follow-up: [`docs/performance/EV1-evaluation.md`](../performance/EV1-evaluation.md) gives the method and limits. Revisit if a significant disagreement is measured between the judge and a human review on a sample (to do: not measured today), or if the team accepts an evaluation library despite ADR-0001.
