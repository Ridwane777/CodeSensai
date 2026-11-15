# User stories - [EV1] Answer evaluation and hallucination detection

Issue #53. Code: `src/sensai/eval/`, command
`sensai-eval`. Choice and trade-offs:
[ADR-0019](../decisions/0019-llm-judge-evaluation.md). Method, report
format and limits: [docs/performance/EV1-evaluation.md](../performance/EV1-evaluation.md).
Translated from French on 2026-10-29.

A second model call (the "judge") rates each answer from 1 to 5 for relevance
and coherence, and checks each claim of the answer against reference
passages. **These scores are a model's estimates, not measurements**; the
criteria below describe what is observed, not a guarantee that the judge is
right.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `sensai-eval run` on 5 cases: qwen3:8b ✅ (25 min); qwen3-coder:30b ✅ (19 s; relevance 3.40/5, coherence 5.00/5, faithfulness 0.42).

## US-EV1-1 - Know whether a new prompt improves or degrades the answers
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who changes the system prompt (A4),
**I want** to run the same set of questions before and after the change and compare both results,
**so that** I decide with numbers rather than by eye.

**Acceptance criteria:**
- `sensai-eval run --dataset … --out a.json --generate` makes the agent answer the dataset's questions and writes a JSON report; after `sensai-prompt use system v2`, the same command writes `b.json`.
- Each report states the system prompt version used (`generator.system_prompt_version`), the judge model, the version and hash of the judge prompt, the dataset hash and the date.
- `sensai-eval compare a.json b.json` shows, for relevance, coherence, faithfulness, the share of flagged claims and the number of judge errors, the values of A, of B and the difference B minus A, then the differences case by case.
- Cases present in only one of the two reports are listed, not silently ignored.

## US-EV1-2 - See which claims are doubtful, and which passage to look at
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who receives a report,
**I want** to see, for each answer, the contradicted or unverifiable claims with the cited passage,
**so that** I check for myself instead of trusting an overall score.

**Acceptance criteria:**
- Each judged case lists its claims with a verdict `SUPPORTED`, `CONTRADICTED` or `UNVERIFIABLE`, the ids of the cited passages and a sentence of explanation.
- A case's `flagged` list contains exactly the `CONTRADICTED` and `UNVERIFIABLE` claims, with, for each citation, the file and lines of the passage when they exist.
- If the judge cites a passage that does not exist, or cites nothing for a `SUPPORTED` or `CONTRADICTED` verdict, the claim becomes `UNVERIFIABLE` with the flag `citation_invalide`; the original verdict stays visible.
- With no passage supplied, no claim is declared supported (the example's `sans-source` case: the judge must not use its own knowledge).
- A case's faithfulness is the share of `SUPPORTED` claims; it is empty (`null`) when the answer has no claim to check, and never counted as 0 or 1.

## US-EV1-3 - A judge failure must not pass for a bad answer
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who runs the evaluation on a small local model,
**I want** unusable judge outputs to be retried, then counted separately,
**so that** averages are not skewed by technical failures.

**Acceptance criteria:**
- An output that is not valid JSON, or whose score is outside 1 to 5, is sent back to the judge with a corrective message, up to 2 times.
- If it stays unusable (or if Ollama is unreachable), the case becomes `judge_error` with the error and the start of the raw output; the command does not crash.
- A case in error is never scored 0: it is excluded from the averages and counted in `summary.judge_errors`, which the displayed summary mentions.
- A case with no answer (and without `--generate`) is `skipped`, also counted separately.

## US-EV1-4 - Do not compare two reports that do not measure the same thing
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead comparing two reports made at different times,
**I want** to be warned when the judge, its prompt, the data or the origin of the passages changed,
**so that** I do not take a change of judge for an improvement of the agent.

**Acceptance criteria:**
- `sensai-eval compare` writes `comparable: false` and one sentence per differing setting (judge model, judge prompt, dataset, passage origin); the differences are still computed.
- `--strict` makes the command exit with code 1 in that case (usable in CI); without `--strict`, the code is 0.
- An invalid dataset is refused before any judge call, with the number of the faulty line.

---

**Not done:** no comparison between the judge and a human review has been
made; the judge's reliability is therefore not measured (see the limits in
the evaluation document). The `--sources rag` mode was only tested with a
simulated index in the tests.

## US-EV1-5 - Run an evaluation from the chat
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead presenting the agent to the team,
**I want** to type `/eval run --dataset … --out …` in the conversation,
**so that** I show the EV1 evaluation without leaving the agent.

**Acceptance criteria:**
- The session's model is used as judge and its host as server, unless I give `--judge-model` or `--host`.
- `/eval compare rapport_a.json rapport_b.json` works without calling a model.
- The report is identical to the one from `sensai-eval` (same code, ADR-0028); a malformed command shows the error and the chat goes on.
- Written limit: the evaluation blocks the chat until it ends (Ctrl+C to interrupt it).

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): the Quality page button "Evaluate the latest answer" calls `POST /api/sessions/{id}/evaluate`, which judges the last answer with the `sensai-eval` judge (relevance and coherence 1-5, faithfulness 0-1 or `null` without project passages, flagged claims). One extra model call, on demand only, never at every turn. With the real server the demo rows are hidden. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): "Evaluate the latest answer" added a "Evaluated answer #1" row (API: relevance 5, coherence 5, faithfulness 1.0 on 4 passages).


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-EV1-1 | ✅ | `eval/cli.py`, `eval/report.py` | `tests/eval/test_report.py`, `tests/eval/test_cli.py` |  |
| US-EV1-2 | ✅ | `eval/judge.py` | `tests/eval/test_judge.py` |  |
| US-EV1-3 | ✅ | `eval/judge.py` | `tests/eval/test_judge.py`, `tests/eval/test_report.py::test_generation_failure_does_not_crash` |  |
| US-EV1-4 | ✅ | `eval/report.py`, `eval/dataset.py` | `tests/eval/test_report.py`, `tests/eval/test_dataset.py` |  |
| US-EV1-5 | ✅ | `chat_commands.py` (`/eval`) | `tests/test_chat_commands.py` | The judge's reliability against a human review is still not measured (written above) |
