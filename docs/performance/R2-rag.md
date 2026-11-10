# R2 — Advanced RAG: measurements

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: the end-to-end RAG scenario passes with both models (see R1); the ranking measurements below are not redone by that trial. Earlier measurements below.

Decision: [ADR-0032](../decisions/0032-hybrid-rag-and-reranking.md).
User stories: [R2-advanced-rag.md](../user-stories/R2-advanced-rag.md).
Script: [`scripts/bench_rerank.py`](../../scripts/bench_rerank.py).

## Method

- **Date**: 2026-10-17.
- **Machines**: client on an Intel i7-1355U laptop (12 threads). Ollama 0.40.6 on a RunPod pod, with `bge-m3` (embeddings) and `qwen3-coder:30b` (reranking).
- **Index**: the repo itself, split as in R1, i.e. **2,001 passages**. Files that contain the questions or their expected answers (`docs/performance/`, the measurement scripts, the R2 user stories) are removed from the index: otherwise search would find the question instead of the answer.
- **Questions**:
  - the 15 R1 questions (`scripts/bench_rag.py`);
  - 10 **held-out** questions, written before any measurement and covering code added after R1. They check that the choice does not only hold on the R1 set;
  - the 3 **unanswerable** R1 questions (Kafka, Stripe, e-mails).
- **Criteria**:
  - right file in 1st position;
  - right file in the top 5;
  - MRR (1 / rank of the right file, averaged);
  - seconds per question.

```bash
python scripts/bench_rerank.py --host <Ollama host> --out r2.json   # the 4 variants
python scripts/bench_rerank.py --host <Ollama host> --production    # the shipped code
```

## Variant comparison (threshold disabled, 50 candidates)

| Method | R1: 1st / top 5 / MRR | Held-out: 1st / top 5 / MRR | s/question |
| --- | --- | --- | --- |
| dense (R1 as is) | 5 / 12 / 0.541 | 3 / 8 / 0.514 | 1.07–1.74 |
| BM25 only | 6 / 11 / 0.551 | 4 / 7 / 0.519 | 1.17–1.20 |
| hybrid (RRF, k = 60) | 7 / 15 / 0.669 | 3 / 7 / 0.492 | 1.18–1.25 |
| hybrid + model reranking | **12 / 15 / 0.883** | **7 / 9 / 0.759** | 4.36–4.43 |

**Careful when comparing with R1.** R1 reported 11/15 in 1st position. Here
the same dense search gets 5/15, because the measurement documents (which
copied the questions) are excluded from the index. The two figures are not
comparable. All R2 comparisons are made under the same conditions, with
those files excluded.

## The shipped code (`--production`)

Configuration: `RagIndex.search` with `LlmReranker`, the default threshold
0.54 and 5 passages, as in the CLI.

| Set | 1st | top 5 | s/question |
| --- | --- | --- | --- |
| R1 (15) | 11 | 13 | 4.13 |
| Held-out (10) | 8 | 9 | 4.58 |
| Unanswerable (3) | 0 passages for each ✅ | | |

User-story criteria:
- **US-R2-1**: beat R1's 11/15. The fair comparison is against dense search under the same conditions: 5/15 → 11/15, and 3/10 → 8/10 on the held-out set.
- **US-R2-3**: no passage is returned for the 3 unanswerable questions.

The shipped code gets 13/15 in the top 5, against 15/15 for the variant
without a threshold: with the threshold at 0.54, two questions lose their
right passage before reranking. That is the price of returning nothing for
unanswerable questions.

## The threshold

| | Dense score |
| --- | --- |
| Best passage, unanswerable questions | 0.437; 0.503; **0.530** |
| Best passage, the 3 weakest real questions | **0.553**; 0.558; 0.570 |

The threshold moves from 0.50 to **0.54**, between the two. **The margin is
only 0.02:** a differently worded question can land on the wrong side. With
3 unanswerable questions, the sample is too small to set the threshold more
precisely. It can be tuned with `--rag-min-score`.

## Limits and next steps

- **Time:** reranking adds about 3 s to each question, since automatic retrieval runs on every turn. `--no-rag-rerank` (or `"rag_rerank": false` in `config.json`) turns it off.
- **Model:** the results hold for `qwen3-coder:30b`. Another chat model needs a new measurement.
- **Set size:** 25 questions is few. One point of difference is a single question.
- **BM25 recomputed:** the BM25 index is recomputed in memory after each update (2,001 passages, imperceptible time). To revisit beyond a few tens of thousands of passages, e.g. with SQLite FTS5.
- **Not measured yet:** the effect of the `kind` and `path` filters on quality. They are only unit-tested.
