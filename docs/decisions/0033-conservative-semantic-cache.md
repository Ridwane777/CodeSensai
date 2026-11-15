# ADR-0033 - Conservative semantic cache: bge-m3 embeddings, "decisive words" rules and a 0.90 threshold (A6)

- **Status**: Accepted; amended by ADR-0056 (2026-11-02: cache disabled by default)
- **Date**: 2026-10-18
- **Deciders**: Ridwane (Workstream C), after measurement and threshold validation
- **Workstream**: C (Memory); the CLI (shared file) displays served responses

## Context
A6 requires to "cache responses and serve them directly for
semantically similar queries (embedding comparison), without calling
the model". What is done elsewhere (Redis LangCache, GPTCache, LiteLLM):
embeddings, then a similarity threshold. The same sources point out the
main risk, the false positive, and LiteLLM advises excluding agent loops
and multi-turn conversations from the cache.

Measurement (`scripts/bench_cache.py`) on two sets written before the relevant
measurements: 39 rephrasings, which should be served, and 48 traps,
which must never be ("maximum size" vs "minimum", "read" vs
"write a file", "Python" vs "JavaScript").

| Method | Trap-free threshold | Rephrasings served | Traps served | Chat model call |
| --- | --- | --- | --- | --- |
| bge-m3 alone | 0.934 | 4/39 | 0/48 | no |
| qwen3-embedding:0.6b alone | 0.948 | 1/39 | 0/48 | no |
| nomic-embed-text alone | 0.965 | 0/39 | 0/48 | no |
| bge-m3 + rules | 0.876 (chosen: 0.90) | 10/39 (7/39 at 0.90) | 0/48 | no |
| bge-m3 + yes/no check by qwen3-coder (set 1 only) | 0.60 | 21/25 | 1/28 | yes, ~1.2 s |

With bge-m3 alone, one trap reaches 0.92 ("maximum size" vs "minimum"),
while honest rephrasings go as low as 0.59: no threshold
separates the two.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Embeddings only, low threshold (0.70) | Matches the catalog literally; serves 34/39 rephrasings | Serves 34/48 traps: confidently wrong answers |
| Embeddings only, safe threshold (0.934) | Literal; no error measured | Serves 4/39 rephrasings: the cache almost never serves |
| Another embedding model (qwen3-embedding, nomic) | Nothing to code | Measured worse than bge-m3 |
| Embeddings, then a check by the chat model | 21/25 served | 1 trap served; calls the model (contrary to the letter of the feature); ~1.5 s per response |
| **bge-m3 embeddings + "decisive words" rules, 0.90 threshold** | No trap on either set; no chat model call; reuses the RAG model | Serves only 7/39 rephrasings (18%) |

The rules (`knowledge/cache.py`, `conflict`) reject two questions that
do not share the same names (code identifiers, words with a capital letter or
digit) or the same action families (create, read, write, delete,
enable, disable, start, stop, increase, reduce…).

## Decision
bge-m3 embeddings, "decisive words" rules, 0.90 threshold (margin above
the strongest trap measured, 0.876). An entry is served only if it has the
same project and the same chat model, has not expired, and the files
the response relied on have not changed. Never cached:
turns where the agent wrote or executed, and questions that depend on the
conversation.

## Consequences
- ✅ No trap served out of 48 measured; no chat model call for a served response.
- ✅ No new model: bge-m3 is already used by the RAG.
- ❌ The cache is conservative: about one rephrasing in five is served; the others go back to the model.
- ❌ The rules are word lists (French and English): an opposite missing from the list gets through if similarity exceeds 0.90. 48 traps is not much.
- ❌ The author of the rules had seen both sets: the second was written before the rules, but it is not fully independent.
- ❌ One more embedding call per question (a few tenths of a second).
- Follow-up: `docs/performance/A6-cache.md`, `scripts/bench_cache.py`. Revisit if a real trap gets through, or for the model check if the team agrees to depart from the letter of the feature.
