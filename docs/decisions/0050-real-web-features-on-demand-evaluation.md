# ADR-0050 — Web interface: M2, M4 and A2 data streamed as SSE events, EV1 evaluation on demand, X5 tasks edited from the web but run by `sensai-schedule`

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-10-29
- **Deciders**: Ridwane (Lot C), on behalf of Lot D — to be confirmed by the team
- **Lot concerned**: D (`src/sensai/web/runtime.py`, `src/sensai/web/server.py`, `frontend/src/engine/wire.ts`, `frontend/src/pages/Quality.tsx`, `frontend/src/pages/Planning.tsx`)

## Context

With the real server, several parts of the interface were still played from
demo data: the token bar and compression (M2), the Artefact panel (M4), the
sub-agents' own steps (A2), the Quality page scores (EV1) and the Planning
page (X5). The CLI already had the real code for each of them. The question
was how to bring it to the web without making each answer slower and without
running background jobs inside the web server.

## Options considered

**Data of a turn (M2, M4, A2)**

| Option | Pros | Cons |
| --- | --- | --- |
| **New SSE events in the turn stream** (chosen): `usage`, `compression`, `artifact_patch`, `subagent_step` | Same channel as the other events ([ADR-0022](0022-transport-sse-et-modele-d-execution.md)); shown live; no extra request | More event types to keep in sync between `runtime.py` and `wire.ts` |
| Polling routes (`GET /usage`, `GET /state` after each turn) | Simple server side | Not live; extra requests; sub-agent steps lost between two polls |

**Evaluation of an answer (EV1)**

| Option | Pros | Cons |
| --- | --- | --- |
| Judge every turn automatically | Scores always there | One more model call per answer: roughly doubles the answer time with a local model |
| **On demand: "Évaluer la dernière réponse"** (chosen), `POST /api/sessions/{id}/evaluate` | Costs nothing until asked; same judge as `sensai-eval` | The user must click; one model call per evaluation |
| Terminal only (`sensai-eval`) | No web code | The Quality page stays demo data |

**Scheduled tasks (X5)**

| Option | Pros | Cons |
| --- | --- | --- |
| **The web edits `<data_dir>/schedule/tasks.json`, `sensai-schedule` runs the tasks** (chosen) | One executor, the one already tested; the web server stays a request/response server | Tasks do not run unless `sensai-schedule loop` (or `run-due`) runs |
| The web server runs the tasks in a background thread | Nothing else to start | Two executors on the same file; tasks stop when the tab's server stops; harder to test |

## Decision

- Each turn emits `usage` (`used`, `budget`, `num_ctx`, `estimated: true`)
  before the answer, `compression` (`saved_tokens`) when the sliding summary
  ran, one `artifact_patch` (`section`, `markdown`) per section of the state
  document changed by `update_state`, and one `subagent_step` (`agent`,
  `tool`, `arguments`, `ok`, `content`) per tool run by a sub-agent
  (`delegate_task` and every `team_task` role). `GET /api/state` also returns
  `bodies` so the Artefact panel is filled at load. Few-shot (A7) uses the
  same settings as the CLI and emits `fewshot`.
- EV1 is **on demand**: `POST /api/sessions/{id}/evaluate` judges the last
  answer with the `sensai-eval` judge (relevance and coherence 1-5,
  faithfulness 0-1 or null without project passages).
- X5: four token-protected routes under `/api/schedule/tasks` read and write
  the same file as `sensai-schedule`; the web server never runs a task, and
  the Planning page says to run `sensai-schedule loop`.

## Consequences

- ✅ The token bar, compression notice, Artefact panel, sub-agent steps,
  Quality scores and Planning list now come from the real agent code.
- ✅ No answer is slowed down by the judge; no second task executor.
- ❌ Token counts are **estimates** (characters / 4, [ADR-0045](0045-token-budget-sliding-summary.md)), not the model's real count.
- ❌ An evaluation costs one more model call and the user has to click for it.
- ❌ Scheduled tasks do not run unless `sensai-schedule loop` is started separately.
- ❌ A sub-agent step's `content` is cut at 600 characters (already filtered by the gateway).
- ❌ None of this was tried with the real model (`qwen3-coder:30b`): tested with pytest (scripted model) and vitest only.
