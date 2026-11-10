# A6 — Semantic cache: measurements and real trial

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: same question twice with the cache on: qwen3:8b on CPU 5 min 37 then **0.5 s** from the cache; qwen3-coder:30b on GPU 9.0 s then **1.8 s**. Identical question only: the rephrasing measurements below still stand. Earlier measurements below.

Decision: [ADR-0033](../decisions/0033-conservative-semantic-cache.md).
User stories: [A6-semantic-cache.md](../user-stories/A6-semantic-cache.md).
Script: [`scripts/bench_cache.py`](../../scripts/bench_cache.py).

## 1. The threshold: rephrasings versus traps

**Method** (2026-10-18). Ollama 0.40.6 on a RunPod pod, client on an Intel
i7-1355U laptop.

- **Questions**: two sets of developer questions (written in French). Each
  original question comes with rephrasings, which should be served, and
  traps, which must never be: same topic, but a different action, object or
  name.
- **Set 1** (25 rephrasings, 28 traps): written before any measurement.
- **Held-out set** (14 rephrasings, 20 traps): written after the first
  measurement, but before writing the rules.
- **Measurement**: cosine similarity between the original question and each
  other question.

```bash
python scripts/bench_cache.py --host <Ollama host> --model bge-m3 --out a6.json
```

**Result 1: embeddings alone do not separate the two.**

| bge-m3 | Score |
| --- | --- |
| Strongest trap: "**maximum**" / "**minimum** size of an indexed file" | 0.925 |
| Then "**read**" / "**write** a file with the agent" | 0.907 |
| Then "**enable**" / "**disable** debug mode" | 0.895 |
| Weakest rephrasing: "enable debug mode" / "get more logs" | 0.588 |

**Result 2: three embedding models, with or without the rules.** For each
row, we take the lowest threshold that serves no trap on both sets combined
(48 traps), then count the rephrasings served.

| Model | Alone: threshold, rephrasings served | With the rules: threshold, rephrasings served |
| --- | --- | --- |
| **bge-m3** | 0.934; 4/39 | **0.876; 10/39** |
| qwen3-embedding:0.6b | 0.948; 1/39 | 0.862; 9/39 (first version of the rules) |
| nomic-embed-text | 0.965; 0/39 | 0.908; 5/39 (first version of the rules) |

The rules (`knowledge/cache.py`, `conflict`) refuse two questions whose
names (code identifiers, words with a capital letter or a digit) or action
families (create, read, write, delete, enable, disable, start, stop,
increase, reduce…) differ. After measuring the three models, "combien" and
"nombre" ("how many", "number") were removed from the "count" family: they
are question words, which blocked honest rephrasings. bge-m3 was re-measured
with the corrected rules (table 3); the other two models were not.

**Result 3: bge-m3 and the corrected rules, by threshold** (both sets
combined).

| Threshold | Rephrasings served | Traps served |
| --- | --- | --- |
| 0.70 | 19/39 | 8/48 |
| 0.80 | 16/39 | 5/48 |
| 0.85 | 12/39 | 2/48 |
| **0.90 (chosen)** | **7/39 (18 %)** | **0/48** |
| 0.94 | 2/39 | 0/48 |

The threshold is set to 0.90 rather than the measured minimum (0.876, "what
does `load_settings` return" / "which parameters does `load_settings` take"),
to keep a margin on unseen questions.

**Rejected variant: verification by the chat model.** The embeddings propose
a candidate, then qwen3-coder answers yes or no to "same question?". On set
1, it serves 21/25 rephrasings and 1/28 trap, for ~1.2 s more. It is
rejected because it calls the model, which goes against the letter of the
feature, and because it serves 1 trap (ADR-0033).

## 2. Real trial in the CLI (2026-10-18)

`sensai --model qwen3-coder:30b --host <pod>` run in this repository (2,235
indexed passages), with five inputs in a row (asked in French):

| Input | Result |
| --- | --- |
| "How do I run the project's tests?" | Model answer in 16.8 s, saved |
| The same question | **Served from the cache** (similarity 1.00), with the original question and its date |
| "How do I go about running the project's tests?" | **Served from the cache** (similarity 0.92) |
| "How do I skip a failing test?" (trap) | **Not served**: model answer (`@pytest.mark.skip`…) in 11.3 s |
| `/cache` | "2 answer(s) in memory, served 2 time(s), about 34 s saved" |

**Time of a served answer**: the same lookup (`AnswerCache.lookup`) was
repeated 10 times on the trial's database. Median **1.06 s**, maximum
1.37 s, versus 16.8 s for the model's answer. Almost all of that time is the
round trip to the pod for the question's embedding, through RunPod's HTTPS
proxy; the database search is negligible.

## 3. User story criteria

| Criterion | Status |
| --- | --- |
| US-A6-1: a rephrasing served in under one second, without calling the chat model | **Not met for time**: 1.06 s median with the remote pod. The chat model call is indeed avoided. With Ollama on the same machine, the network round trip disappears (not measured here) |
| US-A6-1: served-answer rate measured | 7/39 rephrasings (18 %) at the chosen threshold |
| US-A6-2: no trap served | 0/48 at threshold 0.90 |
| US-A6-2: invalidation when a source file changes | Tested (`tests/knowledge/test_cache.py`) |
| US-A6-2: no caching after a write or an execution, nor for a question that depends on the conversation | Tested (only `read_file` and `search_codebase` are allowed; `standalone`) |
| US-A6-3: notice, original question and date; `/again`, `/cache`, `/cache clear` | Seen in the real trial and tested |

## 4. Limits

- **A conservative cache**: about one rephrasing in five is served. Synonyms missing from the lists ("switch to" for "enable") make a real rephrasing get refused.
- **Small sets**: 48 traps and 39 rephrasings. An opposite missing from the lists gets through if the similarity exceeds 0.90.
- **Sets not fully independent**: the author of the rules had seen both sets. The second was written before the rules.
- **Defects are served again**: a cached answer is replayed as is, defects included. In the trial, the first answer wrongly cited a test on `requirements.pdf`. `/again` asks the model again and replaces the entry.
- **Fact memory is not tracked**: the cache tracks the files read by the answer and `SENSAI.md`, not the fact memory (M3) or the profile. An answer based on `recall_facts` is never cached, but the system prompt contains the list of known entities.
- **Expiry happens on read**: an entry older than 30 days is removed when a question finds it. Entries no question finds stay in `~/.sensai/cache.db` until `/cache clear`.
