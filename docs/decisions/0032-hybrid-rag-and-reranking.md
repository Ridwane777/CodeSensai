# ADR-0032 — Advanced RAG: hybrid search, RRF fusion and reranking by the model (R2)

- **Status**: Accepted
- **Date**: 2026-10-17
- **Deciders**: Ridwane (Workstream C), choice delegated then backed by a measurement
- **Workstream**: C (Memory); no other workstream affected (the `search_codebase` tool keeps its name)

## Context
R1 retrieves passages by embedding similarity alone (bge-m3).
It misses exact names (`FactStore`, `memory.db`) and the right file does not come
first often enough. R2 requires reranking, metadata filters
and a per-passage score (US-R2-1 to 3).

Constraints: no LLM framework, Ollama 0.40.6 **has no `/api/rerank`**
(404 measured), and a single GPU machine (the pod) shared with the chat model.

Measurement (`scripts/bench_rerank.py`, real index, files containing the
questions excluded) on 15 R1 questions and 10 held-out questions,
written before the measurement:

| Method | R1: 1st / top 5 / MRR | Held-out: 1st / top 5 / MRR | s/question |
| --- | --- | --- | --- |
| dense (R1) | 5 / 12 / 0.54 | 3 / 8 / 0.51 | 1.1–1.7 |
| BM25 | 6 / 11 / 0.55 | 4 / 7 / 0.52 | 1.2 |
| hybrid RRF | 7 / 15 / 0.67 | 3 / 7 / 0.49 | 1.2 |
| hybrid + model | 12 / 15 / 0.88 | 7 / 9 / 0.76 | 4.4 |

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Keep dense only (R1) | No work, fast | 5/15 in 1st position |
| BM25 only | No embeddings, finds exact names | No synonyms, no better than dense |
| Hybrid BM25 + dense, RRF fusion (k=60, Cormack et al. 2009) | Fast, no tuning, 15/15 in the top 5 on R1 | No gain on the held-out set |
| Dedicated cross-encoder (bge-reranker) | Standard method, fast once loaded | Ollama does not expose it: it would take one more server or local torch |
| Hybrid then reranking of the top 10 by the chat model, in a single call | Only net gain on both sets (1st: 5→12 and 3→7); no extra dependency | +3 s per search, loads the chat model |

## Decision
Hybrid BM25 + embeddings fused by RRF, then the chat model reranks the
top 10 passages (JSON response). If the model fails (timeout, invalid JSON),
the fusion order is kept. Reranking can be turned off in configuration.

## Consequences
- ✅ The right file comes first 12 times out of 15 (versus 5) and 7 times out of 10 on the held-out set (versus 3).
- ✅ No new dependency: BM25 and RRF are about 80 lines of pure Python.
- ❌ About 3 s more per search, and one more call to the chat model (GPU cost).
- ❌ The result depends on the chat model: another model will need a new measurement.
- ❌ The score threshold (US-R2-3) has a very thin margin: the best unanswerable question reaches 0.53 and the weakest real question 0.553.
- ❌ The BM25 index is recomputed in memory on load (acceptable for a few thousand passages, to revisit beyond ~50,000).
- Follow-up: `docs/performance/R2-rag.md`, `scripts/bench_rerank.py`. Revisit if Ollama adds `/api/rerank` or if the latency becomes a problem.
