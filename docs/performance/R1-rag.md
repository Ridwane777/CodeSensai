# Performance measurements — [R1] Basic RAG

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: "where is `maximum` defined?": ✅ `stats.py:6` with both models, qwen3:8b on CPU 7 min 41, qwen3-coder:30b on GPU 57 s, indexing included. Earlier measurements below.

Measurements taken on 2026-10-11 to settle three decisions of
[ADR-0009](../decisions/0009-rag-over-the-codebase.md): the embedding model
(decision 2), the search method (decision 1) and the "nothing found"
threshold (decision 8).

Script: [`scripts/bench_rag.py`](../../scripts/bench_rag.py). Raw results:
[`data/R1-quality-2026-10-11.json`](data/R1-quality-2026-10-11.json) and
[`data/R1-search-2026-10-11.json`](data/R1-search-2026-10-11.json).

## Reproduce

```bash
pip install -e ".[dev]" numpy
ollama pull nomic-embed-text && ollama pull qwen3-embedding:0.6b && ollama pull bge-m3
python scripts/bench_rag.py quality --out quality.json   # measurement A
python scripts/bench_rag.py search  --out search.json    # measurement B
```

The corpus for measurement A is `git ls-files`, so results depend on the
commit measured. The figures below are for branch `lot-c/rag` at commit
`9a9724e` (M1 complete, R1 not yet written).

## Machines

| | Measurement machine (results below) | First attempt (abandoned) |
|---|---|---|
| Type | Ubuntu 24.04.4 VM, 8 vCPU AMD EPYC, 23 GB RAM, no GPU | Azure Ubuntu 24.04.5 VM, 2 vCPU AMD EPYC 7763, 7.7 GB RAM, no GPU |
| Software | Python 3.12.3; numpy and Ollama (CPU) installed the same day (pip and official script) | Python 3.12.3, numpy 2.5.4, Ollama 0.40.3 (CPU) |
| Result | Measurements A and B complete | Only `nomic-embed-text` measured (stopped: too slow on 2 vCPU) |

Both VMs were set up for the measurement (Ollama, models, Python environment
in a dedicated folder) and then fully cleaned. The development machine (disk
97% full, no GPU) was not used.

## Measurement A — which embedding model?

**Method**
- Corpus: the 55 text files tracked by git (code, docs, tests, config), split
  into 40-line blocks overlapping by 10, i.e. 106 passages. Each passage
  starts with its file path. Splitting is identical for all models: we
  compare models, not splitting.
- 15 questions in French about the repo, each mapped to the files that
  contain the answer (list in the script). A question passes at rank *k* if
  one of those files appears among the top *k* passages.
- 3 questions whose answer is not in the repo (Kafka, Stripe, e-mails) to
  tune the threshold.
- Each model gets its recommended prefixes (`search_query:` /
  `search_document:` for nomic, an instruction for qwen3-embedding, nothing
  for bge-m3). Normalized vectors, cosine similarity, exhaustive search.

**Results**

| | `nomic-embed-text` | `qwen3-embedding:0.6b` | `bge-m3` |
|---|---|---|---|
| Right file in 1st position | 8/15 | 10/15 | **11/15** |
| In the top 3 | 14/15 | 13/15 | **14/15** |
| In the top 5 | 14/15 | 14/15 | 14/15 |
| MRR (mean reciprocal rank) | 0.716 | 0.774 | **0.842** |
| Indexing the 106 passages | **141 s** | 615 s | 311 s |
| Median time per question (embedding + search) | **104 ms** | 487 ms | 202 ms |
| Model size | **274 MB** | 639 MB | 1.2 GB |

On the first attempt (2 vCPU), `nomic-embed-text` gave the same score (8/15,
14/15) in 178 s: quality does not depend on the machine, time does.

**"Nothing found" threshold** — score of the best passage for each question:

| | Weakest real question | Strongest unanswerable question | Margin |
|---|---|---|---|
| nomic-embed-text | 0.676 | 0.698 | **negative**: no threshold separates them |
| qwen3-embedding:0.6b | 0.540 | 0.515 | 0.025 |
| bge-m3 | 0.524 | 0.467 | **0.057** |

**Questions missed in 1st position with bge-m3**

| Question | Rank of the right file | First passage returned |
|---|---|---|
| Which contract must every agent-callable tool follow? | 2 | ADR-0003 (tool calling) |
| Who must review a change to the tool registry? | 2 | ADR-0002 (tool registry) |
| What happens if the session database is corrupted? | 8 | ADR-0007 |
| What is the maximum number of iterations of the reasoning loop? | 2 | `prompts/react_prompt.txt` |

The corrupted-database question fails with all three models (rank 15, 33 and
8): the answer is only in the code of `cli.py`, and a 40-line block drowns it
in neighboring code. That is the concrete argument for structure-based
splitting (decision 3).

## Measurement B — which search method?

**Method**: random normalized vectors of 1,024 dimensions (bge-m3's size),
top-5 search by dot product over the whole collection. Median time over 20
searches (3 for 100,000 passages), excluding the question embedding.

| Passages | Pure Python | numpy | Ratio |
|---|---|---|---|
| 300 | 24 ms | 0.27 ms | ×90 |
| 2,000 | 192 ms | 1.4 ms | ×130 |
| 20,000 | 1,614 ms | 4.5 ms | ×360 |
| 100,000 | 8,333 ms | 18 ms | ×455 |

Pure Python grows linearly (about 0.08 ms per passage); numpy stays under
20 ms at 100,000 passages.

## Threshold recalibration with the shipped splitter

Measurement A rerun the same day, bge-m3 only, with the real splitter of
`sensai.knowledge.rag` (`--chunker structure`), at commit `22b5262` (R1
written). Raw results: [`data/R1-quality-structure-2026-10-11.json`](data/R1-quality-structure-2026-10-11.json).

```bash
python scripts/bench_rag.py quality --models bge-m3 --chunker structure
```

**Method error fixed.** A first attempt gave 1/15 in 1st position: since the
corpus is `git ls-files`, it now contained the results of the first
measurement, its report and this script — three files that contain the 15
questions word for word. Search found the question instead of the answer.
The script now excludes `docs/performance/` and `scripts/bench_rag.py` from
the corpus (`EXCLUDED_FROM_CORPUS`). A measurement's own files must never be
part of the measured corpus.

| bge-m3 | 40-line blocks (commit `9a9724e`) | Structure (commit `22b5262`) |
|---|---|---|
| Corpus | 55 files, 106 passages | 61 files, 339 passages |
| Right file in 1st position | 11/15 | 6/15 |
| In the top 3 | 14/15 | 14/15 |
| In the top 5 | 14/15 | **15/15** |
| MRR | 0.842 | 0.683 |
| Indexing | 311 s | 433 s |
| Weakest real question | 0.524 | 0.524 |
| Strongest unanswerable question | 0.467 | 0.494 |

**Reading.** The two columns are not strictly comparable: the corpus changed
together with the splitting (R1 code, tests, user stories and ADRs added).
The drop in 1st position mostly comes from relevant passages missing from the
expected-answer list, written for the old repo: "where are inactive sessions
deleted?" returns `src/sensai/cli.py:97`, which triggers the purge; "how is
the session to resume chosen?" returns the M1 user story that describes it.
Real weakness: test files often rank first, because their docstrings describe
behavior better than the code. Real progress: 15/15 in the top 5, and the
corrupted-database question, missed by all three models, rises to rank 4
(rank 8 before).

**Threshold: 0.50 confirmed** (team decision, 2026-10-11). It still separates
all real questions (≥ 0.524) from unanswerable ones (≤ 0.494), but the margin
is down to 0.03. To be re-measured with this script when the repo grows or if
the embedding model changes.

## Real CLI trial

Same machine, commit `22b5262`, chat `qwen3:8b` and embeddings `bge-m3`
served by Ollama on CPU, on the CodeSensai repo itself.

| Check | Result |
|---|---|
| Automatic indexing on the 1st question, with progress | ✅ 67 files, 386 passages |
| "Where is Kafka configured in this project?" | ✅ "No Kafka configuration was found in the analyzed project files." |
| Rerun without changes | ✅ 0 files reindexed |
| Rerun after editing `README.md` | ✅ 1 file reindexed |
| "Where do we check that an unknown session doesn't crash the CLI?", 5 passages (default) | ❌ "Ollama is not responding (timeout)", even with the model already loaded |
| Same question, 2 passages (`--rag-top-k 2`) | ✅ Cites `tests/test_cli_persistence.py:155-160`, the test that checks it; answer in ~6 min 45 on CPU |

**What the trial reveals**
- With 5 passages, the message sent is long: on CPU, qwen3:8b takes more than
  60 s to read it before writing the first word, and `core/ollama_client.py`
  (Workstream A) drops the connection after 60 s.
- Ollama served qwen3:8b with a 4,096-token context window (the default, read
  with `ollama ps`): a long history (M1) plus passages (R1) can be truncated
  without warning.
- With 2 passages, the model claimed that `cli.py` does not explicitly handle
  an unknown session, although it does (`except KeyError`): the `cli.py`
  passage was not retrieved, and the model extrapolated.

## GPU trial (RunPod pod, demo conditions)

ADR-0004 set-up: the code and the CLI run on the development machine, the
model on a RunPod pod reached via `--host` (port 11434 exposed by the RunPod
HTTP proxy). Chat `qwen3-coder:30b` (18.6 GB), embeddings `bge-m3`, Ollama
0.40.3. Pod variables: `OLLAMA_HOST=0.0.0.0`,
`OLLAMA_MODELS=/workspace/ollama`, `OLLAMA_CONTEXT_LENGTH=16384`; `ollama ps`
reported a 32,768-token window for qwen3-coder:30b (21.7 GB of VRAM).
5 passages per question (default setting).

**First pass (commit `4da5de9`)**

| Check | Result |
|---|---|
| Indexing the repo | ✅ 66 files, 387 passages, under 2 min (≈ 7 min on 8 vCPU) |
| Code question, model not loaded yet | ❌ timeout: loading 18.6 GB into the GPU exceeds the client's 60 s |
| Same question, model loaded | ✅ right code and right test cited, answer in a few seconds; ❌ wrong `cli.py` lines (123-127 cited, code at line 112) |
| "Where is Kafka configured?" | ✅ "No Kafka configuration was found" |
| "Hello" / "What is a closure?" | ❌ answer diverted toward the passages ("relevance is 0.51…") |
| Rerun without changes / after a change | ✅ 0 then 1 file reindexed |

Diagnosis of the wrong lines: the passage sent covered `cli.py:97-136`
(function `main` split into windows) and contained the right code; the model
guessed the line, since it cannot count within the passage.

**Fixes (commit `a0dd3b3`)**: each line of a passage is prefixed with its
line number in the file, the score is no longer shown to the model, and the
instruction tells it to ignore unrelated passages and answer normally.

**Second pass (commit `a0dd3b3`, model preloaded)**

| Question | Result |
|---|---|
| "Where do we check that an unknown session doesn't crash the CLI?" | ✅ `src/sensai/cli.py:112-116` (exact) and `tests/test_cli_persistence.py:155-160`, code copied faithfully |
| "Hello, answer in one sentence." | ✅ normal answer |
| "What is a closure in Python?" | ✅ right answer; ⚠️ followed by a useless source (`docs/decisions/TEMPLATE.md:14-15`) |
| "Where is Kafka configured in this project?" | ✅ no configuration found; ⚠️ cites this report, which mentions Kafka |

All 4 questions were answered in 25 s in total. **R1's Definition of Done is
met** on the demo configuration.

Limits of this trial: one pass per question type; the indexed repo contains
its own measurement reports (hence this file being cited for Kafka); the
client's 60 s timeout remains a risk on the first call as long as the model
is not preloaded (preload it before a demo).

## Trial of the `search_codebase` tool with the agent (2026-10-14)
Decision: [ADR-0013](../decisions/0013-wiring-the-rag-tool.md). RunPod pod
(Community Cloud, 24 GB GPU), Ollama 0.40.3, `qwen3-coder:30b` and `bge-m3`,
repo of 139 files (1,074 passages), throwaway data folder.

| Trial | Setting | What the model does | Result |
| --- | --- | --- | --- |
| 1 | default (5 passages added) | Answers without calling the tool: the added passages are enough | Purge correct (`cli.py:167`); places `bge-m3` in `cli.py` instead of `config.py` |
| 2 | `--rag-top-k 1` | Calls `search_codebase` (`"variable DEFAULT_EMBED_MODEL"`), without confirmation | ❌ The tool, also limited to 1 passage, returns the README: the model answers `qwen3:8b`. The result starts with the automatic-passages instruction ("ignore them") |
| 3 | `--rag-top-k 1`, after the fix | Calls the tool twice, once per question, in its own words | ✅ 5 passages per search, presented as a requested search. `_chunk_markdown`, `rag.py:261` (correct); `DEFAULT_EMBED_MODEL` from `rag.py` (correct, cites the usage line 304 instead of the definition, line 42) |

Durations (one measurement): trial 1, 2 min 52 s including the first
indexing; trial 3, 34 s, index already up to date.

What the trial changed: the tool has its own presentation and ignores
`--rag-top-k` (ADR-0013). It also showed that the default value `"bge-m3"`
is written twice (`config.py` and `rag.py`): to be consolidated.

## Conclusions

- **Model: `bge-m3`.** The most accurate, and the only one that leaves a clear
  margin for the "nothing found" threshold; nomic, faster, makes US-R1-3
  impossible.
- **Search: numpy.** Pure Python would do up to ~2,000 passages, but numpy
  keeps search negligible whatever the project size, for a common
  dependency.
- **Threshold: 0.50**, in the middle of the measured range, confirmed with the
  shipped splitter (margin down to 0.03, see above).

## Limits

- 15 questions written by the team, on a single repo and a small corpus
  (106 passages). A gap of one or two questions between models is not
  significant; the gap on the threshold is more so.
- Only 3 unanswerable questions: the threshold is a first estimate.
- Indexing times depend on the machine (8 vCPU here); they will be longer on
  a laptop without a GPU, which matters for a project's first question
  (automatic indexing, decision 5).
- The comparison between splitters is skewed by the corpus changing, and the
  expected-answer list dates from the old repo.
- The real CLI trials (CPU then GPU) cover a few questions: they show the
  feature works, not an average quality.

## Costs

No monetary cost measured for the VMs, provided by a team member; Ollama and
the models are free. The RunPod pod is billed by the hour while it runs
(range from `docs/research/infra-options.md`: $0.20 to $0.70/h for an RTX
3090/4090); the exact trial duration was not recorded. Usage cost for the
user: 1.2 GB of disk for bge-m3, plus the index size (not measured on a real
project — to be added with the implementation).
