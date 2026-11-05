# ADR-0044 — Automated Prompt Optimization (A7): semantic few-shot selection

- **Status**: Accepted
- **Date**: 2026-10-27
- **Deciders**: Fresnel (Lot A)
- **Lot concerned**: A (`knowledge/fewshot.py`, `cli.py`)

## Context

[A7] Automated Prompt Optimization asks to "build prompts dynamically from
context: auto-selected few-shot examples, adaptive reformulation, or
iterative optimization against a quality signal." The catalogue's own
real-world examples are narrower than that wording: DSPy, and "systems that
dynamically select the best few-shot examples based on the incoming
request" — exactly the second item, not reformulation or iterative
optimization.

Constraints from the repo: no LLM framework (ADR-0001), so no DSPy-style
pipeline compiler; embeddings only go through the same Ollama HTTP API
already used for R1's RAG (`knowledge/rag.py`'s `Embedder`/`OllamaEmbedder`).
[EV1] Automated Eval already defines a JSONL case format with `question` and
`answer` (`eval/dataset.py`, ADR-0019) for judge-scored test cases — the same
shape a few-shot example needs.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Semantic few-shot selection: embed a small library of (question, answer) examples, pick the closest to the incoming question, prepend it to the prompt | Matches the catalogue's own real-world example precisely; reuses the existing embedder and the EV1 dataset format as-is — no new file format to design or document; deterministic, cheap (one extra embedding call per question), easy to test without a model | Only as good as the example library a team actually writes and maintains; doesn't touch reformulation or iterative optimization |
| Adaptive reformulation (rewrite the question before sending it) | Closer to the catalogue's full wording | Needs an extra model call per turn (latency, non-determinism) just to decide whether/how to rewrite; much harder to test deterministically than a cosine-similarity lookup |
| Iterative optimization against a quality signal (generate, score with the EV1 judge, retry if low) | Closest to DSPy's own approach | Multiple model calls per question (cost, latency), and a looping "improve until good enough" has no natural stopping rule here without inventing one; a much bigger feature for a single catalogue star |
| Reuse `RagIndex` (R1) itself to store examples, treating them as "files" | Avoids writing a new index class | `RagIndex` is built around scanning, chunking and persisting *project files* (SQLite table keyed by path, git-aware scanning, document conversion) — none of that fits a handful of (question, answer) pairs; forcing examples through it would be a worse fit than writing the ~100-line `FewShotIndex` that only does what's needed |

## Decision

A new, small `FewShotIndex` (`knowledge/fewshot.py`) loads a JSONL file of
examples through `eval.dataset.load_dataset` — the exact EV1 format, so a
team can reuse an existing eval dataset as its few-shot library, or write
one with the same tool they already know. Only cases with a non-empty
`answer` are kept; the rest (plain eval cases without one) are silently
skipped, not an error.

Unlike `RagIndex`, nothing is persisted to SQLite: the example set is small
and expected to change rarely within a session, so it is embedded once in
memory at startup (`open_fewshot_index` in `cli.py`), the same way the A6
answer cache's embedder is set up.

At each question, `FewShotIndex.best_match()` returns the closest example by
cosine similarity, or `None` under a stricter threshold than RAG's
(`DEFAULT_MIN_SCORE = 0.75` vs. RAG's `0.54`): a loosely related example
would actively mislead the model's tone and content, where a loosely
related RAG passage can simply be ignored.

**This 0.75 is an estimate, not a measurement** (review: PR #96) — unlike
RAG's `0.54` and A6's cache threshold, both set from a sweep over real
cases (`docs/performance/R1-rag.md`, `docs/performance/A6-cache.md`).
`scripts/bench_fewshot.py` runs the same kind of sweep for this threshold,
but hasn't been run yet (no `bge-m3`-capable Ollama reachable when this
ADR was written). Run it on the pod and report the result in
`docs/performance/A7-fewshot.md` before treating `0.75` as validated;
until then, treat it as a reasonable guess, not a sourced number.

When a match is found,
`format_example()` prepends it to the user's message — not to the system
prompt, the same way RAG's `format_context()` already attaches retrieved
passages to the question rather than to the system prompt, and not saved to
`history.turns` for the same reason RAG's context isn't: it would make
every saved session grow with examples that no longer apply by the time it
is resumed.

Both A7 (few-shot) and R1 (RAG) can attach their own block to the same
question; `cli.py` joins whichever of the two produced something before the
question itself.

Entirely opt-in: without `fewshot_examples` in `config.json` (or
`--fewshot-examples`), nothing changes for a project that doesn't configure
it — same pattern as A6's cache and R1's RAG.

## Consequences

- ✅ Matches the catalogue's own real-world example precisely, with no new
  embedding infrastructure: the same `OllamaEmbedder` and the same EV1
  dataset format already used elsewhere in the repo.
- ✅ A team can point `fewshot_examples` straight at an existing EV1 dataset
  file and get useful examples for free, provided it has `answer` fields.
- ❌ Adaptive reformulation and iterative optimization against a quality
  signal — both named by the catalogue's wording — are not implemented.
  Revisit as a follow-up ADR if the need is confirmed; this ADR does not
  claim A7 is done to the letter of its full wording, only to its given
  real-world example.
- ❌ The example library is hand-written and hand-maintained; nothing in
  this ADR selects, ranks or retires examples automatically over time —
  that would be an actual DSPy-style optimizer, out of scope here. Today
  this is a nearest-neighbor lookup among hand-written examples, not
  something that *measures and chooses* — calling it "optimization" is
  honest about the catalogue's example, not about the general sense of
  the word (review: PR #96). A low-cost way to earn that word: use the
  EV1 judge, which already exists, to score an evaluation set with and
  without each candidate example offline, keep only examples that improve
  the score, and derive `fewshot_min_score` from that run instead of a
  guess — this would also resolve the threshold-measurement gap above.
  Not implemented here; a real follow-up, not a promise.
- ❌ The web server (`src/sensai/web/runtime.py`) never opens a few-shot
  index: a team running `sensai-web` gets no example attached to any
  question, even with `fewshot_examples` set in `config.json`, although
  [ADR-0035](0035-serveur-web-reel.md) asks for the same agent on both
  sides (review: PR #96). The sub-agents of `delegate_task`/`team_task`
  receive only their task, so they never get an example either. Wiring the
  web side means giving `Runtime` the same `FewShotIndex` and the same
  `filter_output` wrapping; not done here, left as an open gap.
- ❌ `sensai-schedule` (X5) does not read `fewshot_examples` either: an
  unattended scheduled task never gets an example.
- ❌ The A6 answer cache stores an answer that the attached example
  influenced, under a key that ignores the example: a later identical
  question is served that answer even if the example library has since
  changed. Acceptable for the same reason as R1's passages (the cache is
  also invalidated by the files it cites, not by the prompt it was built
  from), but worth knowing when editing the library (review: PR #96).
- ❌ `bge-m3` embeds the same question up to three times per turn when RAG,
  the A6 cache and A7 are all enabled: once each, independently, with no
  shared cache of the computed vector within a turn (review: PR #96).
  Each embedder is wired up separately in `cli.py` for its own feature;
  sharing one embedding would need a small refactor of how `open_rag_index`,
  `open_answer_cache` and `open_fewshot_index` are called, not attempted
  here to keep this ADR's scope to A7 itself.
