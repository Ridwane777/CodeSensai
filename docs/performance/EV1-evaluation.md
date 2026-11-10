# Answer and hallucination evaluation — [EV1]

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `sensai-eval run` on `ev1_sample.jsonl` (5 cases) was run for real: qwen3:8b as model and judge on CPU, report written in 25 min; qwen3-coder:30b on GPU in 19 s, mean relevance **3.40 / 5**, coherence **5.00 / 5**, faithfulness **0.42** (4 cases with claims), 3 claims of 7 flagged. These are a model's estimates, not measurements (see "Limits"). Earlier measurements below.

Method, report format, commands to reproduce and limits of the LLM-judge
evaluation decided in [ADR-0019](../decisions/0019-llm-judge-evaluation.md).
Needs: [EV1 user stories](../user-stories/EV1-evaluation-hallucinations.md).

**Until 2026-11-06, result of a real run: not measured** (see the box above for the real run). No Ollama server was
reachable on the machine where EV1 was written (2026-10-14): everything
tested is tested with a simulated judge (`tests/eval/`), offline. No
relevance, coherence or faithfulness score was therefore given in this
repository. The "Results" section is to be filled in after a real run, with
the machine and models used. What was verified without a server: run without
Ollama, the command writes a report where the 5 sample cases are
`judge_error`, prints the connection error and exits with code 0.

**What these scores are: estimates produced by a model**, not
measurements. See "Limits".

## What the judge evaluates

For each case (a question, an answer, reference passages), a single call to
the judge model (`POST /api/chat`, `stream: false`, `format: "json"`,
`temperature: 0`, `seed: 42`) returns:

| Field | Content |
| --- | --- |
| `relevance` | integer from 1 to 5: does the answer address the question? |
| `coherence` | integer from 1 to 5: is the answer clear and free of internal contradiction? |
| `claims` | list of claims: `text`, `verdict`, `sources` (ids `S1`…), `explanation` |

The anchors of each level (1 to 5) are in the prompt
[`prompts/judge/v1.txt`](../../prompts/judge/v1.txt). Relevance and coherence
ignore factual accuracy: that is the role of faithfulness.

**Verdicts for a claim** (based only on the passages provided):

| Verdict | Meaning |
| --- | --- |
| `SUPPORTED` | a passage says the same thing or directly implies it |
| `CONTRADICTED` | a passage says the opposite |
| `UNVERIFIABLE` | no passage settles it (even if the claim is true in the world) |

**Faithfulness** (computed by `eval/judge.py:faithfulness`, not by the model) =
`SUPPORTED` claims / total claims of the case; `null` with no claim.
Mean faithfulness covers the cases that have one (`n_faithfulness` gives
their number).

**Code guardrails on the judge's output:**
- Tolerant JSON extraction: ```` ```json ```` fences removed, from the first `{` to the last `}`.
- Scores outside 1 to 5, or not integers; unknown verdict; `claims` missing: output refused and retried (at most 2 retries, with the faulty output and a corrective message).
- `SUPPORTED` or `CONTRADICTED` without a citation, or with an id not in the passages: the claim becomes `UNVERIFIABLE`, with the flag `citation_invalide` and `verdict_original`.
- Still unusable, or `OllamaError`: the case is `judge_error` (start of the raw output kept, at most 2,000 characters). No score of 0, no mean.

**Flagged cases (`flagged`)**: all `CONTRADICTED` or `UNVERIFIABLE` claims
of the case, with their citations (id, file, lines).

## The dataset

JSONL file, one line per case (`eval/dataset.py`):

| Key | | |
| --- | --- | --- |
| `id` | required, unique | |
| `question` | required | |
| `answer` | optional | answer to judge; without it, `--generate` makes the agent answer, otherwise the case is `skipped` |
| `sources` | optional | list of texts, or of `{"source", "text"}` objects; ignored with `--sources rag` |
| `notes` | optional | what the case should show |

An unknown key, a duplicate id, invalid JSON: an error naming the line.

[`datasets/eval/ev1_sample.jsonl`](../../datasets/eval/ev1_sample.jsonl) contains
5 hand-written cases, with invented, self-contained passages (they are not
excerpts from this repository). Each case targets one situation; the
"intent" column is what the author expects from the judge, **not an observed
result**:

| `id` | Situation | Intent |
| --- | --- | --- |
| `fidele` | answer fully supported by the source | `SUPPORTED` claims, faithfulness 1 |
| `contredit` | the answer says 7 days, the source 30 | one `CONTRADICTED` claim |
| `inverifiable` | one supported sentence, one (BM25 reranking) absent from the source | one `UNVERIFIABLE` claim |
| `off-topic` | coherent answer but unrelated to the question | low relevance, high coherence |
| `sans-source` | no passage provided | `UNVERIFIABLE` claim |

Five cases support no statistical conclusion: they check that the pipeline
works and that the judge reacts to obvious situations.

## Origin of the passages

- `--sources dataset` (default): the `sources` of each line. Deterministic.
- `--sources rag`: the current project's index (R1), opened by the same function as the CLI (`cli.open_rag_index`), with `rag_model`, `rag_top_k` and `rag_min_score` from `config.json` or their defaults. It first indexes the project (several minutes the first time) and requires the embedding model (`bge-m3`). Only the `.search(query, top_k, min_score)` contract is used by `eval/sources.py:rag_sources`. The tests only use a fake index.

## Report format

JSON file written by `sensai-eval run` (`eval/report.py:run_eval`):

| Key | Content |
| --- | --- |
| `schema_version` | `1` |
| `created_at`, `sensai_version` | UTC date; package version (`inconnue` if it is not installed) |
| `judge` | `model`, `host`, `prompt_name` (`judge`), `prompt_version`, `prompt_sha256`, `temperature`, `seed`, `max_retries` |
| `dataset` | `path`, `sha256`, `n_cases` |
| `sources_mode` | `dataset` or `rag` |
| `generator` | `model`, `host`, `system_prompt_version` if `--generate`, otherwise `null` |
| `summary` | `n_cases`, `n_scored`, `judge_errors`, `skipped`, `source_errors`, `generation_errors`, `mean_relevance`, `mean_coherence`, `mean_faithfulness`, `n_faithfulness`, `claims_total`, `claims_flagged`, `flagged_claim_rate` |
| `cases[]` | `id`, `question`, `answer`, `answer_origin` (`dataset`/`generated`), `passages` (text truncated to 1,000 characters), `status`, then `scores`, `claims`, `flagged`, `attempts` (judged case) or `error`/`raw` (on error) |

`status`: `ok`, `judge_error`, `skipped`, `source_error` (passage search
failed), `generation_error` (generation failed or empty).
**Means only cover `ok` cases.** `flagged_claim_rate` = flagged claims /
total claims, over `ok` cases.

## Comparing two reports

`sensai-eval compare A.json B.json [--out D.json] [--strict]`: differences
**B minus A** in relevance, coherence, faithfulness, share of flagged claims
and number of judge errors, then per-case differences on shared `id`s (`id`s
present on only one side are listed). `comparable` is `false`, with one
warning per setting, if any of these differ: the judge model, the judge
prompt's sha256, the dataset's sha256, the passage origin or
`schema_version`. The generator (model, system prompt) is what is being
compared: it does not block. Exit code 0, except `--strict` with
non-comparable reports (1), or an unreadable report (2).

## Reproduce

```bash
pip install -e ".[dev]"
ollama pull qwen3:8b                      # default judge = model from config.json
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out reports/a.json

# Same dataset, another judge (another model to download beforehand):
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out reports/b.json \
    --judge-model <other-model>
sensai-eval compare reports/a.json reports/b.json         # will flag the judge change

# Compare two system prompts (dataset WITHOUT the "answer" key):
sensai-eval run --dataset questions.jsonl --out v1.json --generate
sensai-prompt use system v2
sensai-eval run --dataset questions.jsonl --out v2.json --generate
sensai-eval compare v1.json v2.json --strict
```

Without installing, from the repository: `PYTHONPATH=src python -m sensai.eval.cli …`.
Judge prompt versions: `sensai-prompt history judge`; another version is
chosen with `--judge-prompt-version`. Tests (offline): `pytest tests/eval`.

`--generate`: a single `stream_chat` turn with the active system prompt
(or `system_prompt_path` from `config.json`), the passages and the question,
with the model from `config.json`.

## Results

**Not measured.** To be filled in after a real run, as: machine (CPU/GPU,
RAM), Ollama version, judge model, agent model, date, JSON report attached
in `docs/performance/data/`, duration of the series.

## Limits

- **Self-preference.** By default the judge is the same model as the agent (`qwen3:8b`): it may favour its own phrasing. Absolute scores must be read with this caveat; prefer comparisons with the same judge, or a judge from another family.
- **Judge bias.** An LLM judge may prefer long or confident answers, be swayed by form, or get a subtle technical claim wrong. Its reliability has not been compared with human review: not measured.
- **Residual non-determinism.** Temperature 0 and seed 42 reduce variation but do not remove it (hardware, Ollama version). A small gap between two reports is not a signal; rerunning several times would give an order of magnitude of the noise (not done).
- **Coarse scale.** Integer scores from 1 to 5; on few cases, a mean moves from one case to the next.
- **Unstable claim splitting.** The number of claims varies from one call to the next (and the instruction caps it at 15): a case's faithfulness is a fraction of a few units, very sensitive to one verdict.
- **Language.** The judge prompt and the dataset examples are in English; behaviour with answers or code in other languages is not measured.
- **Passage quality.** The judge is only as good as its passages: in `rag` mode, a missing passage turns a true claim into `UNVERIFIABLE`. This is not a detected hallucination, but an absence of evidence.
- **Injection.** The judged answer is untrusted text; the prompt presents it as data but does not make the judge immune to an answer that gives it orders.
- **Simplified generator.** `--generate` does not run the agent loop (no tools, no memory).
- **Possible silent failure.** The command exits with code 0 even if all cases are `judge_error` (Ollama stopped): read `summary.judge_errors`.
- **`rag` mode not proven for real**: tested only with a fake index.

## Possible improvements

- Measure the judge's agreement with human review on a labelled sample (the prerequisite for putting a numeric confidence on the scores).
- Repeat each case n times and report the spread; a judge from another model family to reduce self-preference.
- A non-zero exit code when no case could be judged, for CI.
- Extend the dataset to real questions about the repository, with passages from the R1 index.
