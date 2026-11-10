# A2 — Multi-agent orchestration: real trials

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `team_task` on `moyenne([])`: qwen3:8b on the laptop CPU ❌ (team does not finish); qwen3-coder:30b on a GPU ✅ 3 of 3 with RAG on (64–73 s), ✅ by hand with RAG off after `list_files` (ADR-0059) and the team fixes (backlog #27); open defects in backlog #28. Earlier measurements below.

Trials run on 2026-10-24 on the RunPod pod (GPU, Ollama), model
`qwen3-coder:30b`, from a Linux workstation (Python 3.12 client). Decisions:
[ADR-0037](../decisions/0037-sub-agent-delegation-tool.md) and
[ADR-0038](../decisions/0038-specialized-agents-and-handoffs.md). Stories:
[A2](../user-stories/A2-multi-agent-orchestration.md).

All figures below are **measured** (no estimates). The samples are small
(2 to 12 trials per case): they show a trend, not a rate reliable to the
percent.

## Scripts to reproduce

| Script | What it measures |
| --- | --- |
| `scripts/bench_a2.py <host> roles\|equipe\|critique\|choix\|detail [n]` | roles, team chain, reviewer, main agent's choice. Works in a temporary folder. |
| `scripts/bench_a2_delegation.py <host> redelegation\|escient\|tardive` | re-delegation, delegating when appropriate (`EXTRA` adds a rule to the prompt, `KINDS` filters), late confirmation. Reads this repository. |
| `scripts/bench_a2_echeance.py <host> durees\|fantome` | duration of a delegation, sub-agent that keeps running after being abandoned |
| `scripts/bench_a2_prompt.py <host>` | the sub-agent with or without the project prompt |

`<host>` is the Ollama server address (never written in the repository).

## 1. Delegation (`delegate_task`): defects found and fixed

| Trial | Before (ADR-0037 code) | After (ADR-0038) |
| --- | --- | --- |
| Duration of a simple delegation (5 tasks) | 6.4 to 36.7 s | 6.2 to 29.9 s (unchanged, expected) |
| Sub-agent after being abandoned by the gateway (8 s deadline) | keeps going until 28.2 s, 797 response chunks lost | stopped at 8.0 s; 0 tool calls and 0 threads afterwards |
| Confirmation after abandonment (10 s deadline) | `write_file` requested at 23.8 s | no confirmation after the stop; returned at 21.2 s (a model call already started finished) |
| Project prompt — remembered fact ("Redis 8") | 1/3 | 3/3 |
| Project prompt — profile ("answer in English") | 0/3 | 2/3 |
| Project prompt — neutral task | 3/3 | 3/3 |
| Re-delegation, tasks that can be split | depth 2: an empty answer in 120 s (3 re-delegations), then 22 to 42 s | depth 1 and tool hidden: 10.7 to 38.3 s, full quality, 0 re-delegations |

Two settings come directly from the measurements:
- **30 s stop margin**: with 5 s, the gateway gave up first, because the
  deadline is only checked between two model responses and a response in
  progress lasted 11 s longer;
- **delegation tool hidden from the sub-agent**: otherwise it tried to
  re-delegate 3 times (refused, but 3 model calls wasted).

## 2. When does the main agent delegate?

5 simple questions (1 file or none) and 5 "splittable" tasks.

| Version | Simple questions delegated | Splittable tasks delegated |
| --- | --- | --- |
| Original description | 1/5 (including `/api/health` delegated twice, 145.9 s) | 1/5 (110.4 s when delegating, 16 to 28 s without) |
| Tightened description alone | 0/5 | 0/5 |
| + orchestration rule in prompt `v2`, run 1 | 0/5 | 4/5 |
| same, run 2 | 1/5 | 3/5 |
| Explicit request ("delegate to a sub-agent…") | — | 6/6 (2 runs) |

Recounted against the rule ("three files or more"): over 2 runs, 6 of 8
tasks citing three files or more are delegated, and 2 of 12 requests that
should not have been are. Delegating costs time: 37 to 120 s versus 13 to
33 s without delegation.

## 3. Specialized agents (roles)

Request made to a role without write access: "create notes.md with write_file".

| Role | Trials | File created | Confirmation requested |
| --- | --- | --- | --- |
| explorer | 5 | 0 | 0 |
| reviewer | 5 | 0 | 0 |

What the model **says** is not always true: once, the explorer answered
"The file notes.md has been created" although nothing was written (it cannot
see the tool). Twice, a role typed the tool call as text (`<tool_call>…`):
the gateway flagged it (`forged_tool_markup`, EV2) and nothing was executed.
The reviewer answers "VALIDATED" to an off-topic request: harmless here (it
cannot write anything), but it is the same tendency as the one fixed in
section 5.

## 4. Handoff (`team_task`)

Throwaway project with `stats.py` (two deliberate bugs). Three verifiable
tasks, the final code is **executed** (assertions): fix `moyenne`, fix
`maximum` for negative numbers, add `mediane`.

| Series | Trials | Final code correct | Path | Duration |
| --- | --- | --- | --- | --- |
| Before the reviewer fix | 9 | 9/9 | explorer → developer → reviewer, validated | 25.2 to 38.4 s |
| Final version | 9 | 9/9 | 8 validated; 1 cut by a RunPod proxy network error (the file had already been written, correctly) | 26.6 to 44.6 s (96.9 s for the network error) |
| "Docstrings" task, full report | 3 | — | validated 3/3, 1 write | 39.1 to 42.0 s |

These tasks are easy: the developer gets them right the first time, so the
correction loop did not trigger in this series. It is covered by the tests
(`tests/tools/test_team_tool.py`) and by section 5.

## 5. Does the reviewer really judge?

The reviewer receives a report claiming "fixed", on a file that is still
wrong (or badly fixed), then on a correct file.

| What the reviewer receives | Wrong work caught | Correct work validated |
| --- | --- | --- |
| the report alone | **0/6** (validated without opening the file, 2 to 4 s) | — |
| + instruction "always read the files" | 0/6 (once 6 reads, and validated anyway) | — |
| **the exact content written** (chosen version) | **6/6** | 5/6 |

The only "needs fixing" on correct work targeted the `moyenne` bug, which
really was still in that file: a real defect, outside the task. Conclusion:
the instruction is not enough, the reviewer must be **given the evidence**.

## 6. Does the main agent hand code to the team?

System prompt `v2`, 5 change requests and 3 questions, 2 runs.

| Rule version | Changes handed to the team | Questions handed to the team |
| --- | --- | --- |
| simple rule | 0/3 | 0/3 |
| "first and only action" rule, requests saying "with write_file" | 1/3 | 0/3 |
| same, requests phrased naturally | **20/20** (4 runs) | **0/12** |

A request handed to the team takes 38 to 65 s, versus 13 to 23 s when the
agent writes alone. One case at 190 s (the team restarted 3 times) led to
returning a finished chain as a result, with the verdict, and not as a
failure: it did not happen again.

## Limits

- Small samples, a single model, a single pod; the code tasks are short (a
  12-line file).
- The whole chain fits within one tool's timeout (120 s): a longer task stops
  before the end (behaviour tested, not observed on the pod).
- The reviewer only sees what was written with `write_file`.
- The `v2` prompt rules steer the model, they do not constrain it:
  spontaneous delegation stays at 6 of 8.
- No load test: a single user, sub-agents one after the other.

## Possible improvements

- Model router (a small model for simple requests): to be measured if a
  second model fits in memory on the pod.
- Let the reviewer run tests in the sandbox, to judge on a result and not
  only by reading.
- A set of harder tasks, where the developer gets it wrong, to measure what
  the correction loop catches.
