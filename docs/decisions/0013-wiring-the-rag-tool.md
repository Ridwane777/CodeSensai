# ADR-0013 — Wire the project search tool to the index opened by the CLI

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Ridwane (Workstream C)
- **Workstream**: C; A impacted (`cli.py`, where each workstream registers its tools)

## Context
ADR-0009 (decision 4) provides two ways to give the project to the model:
passages added automatically to each question, and a tool,
`search_codebase` (`RagTool`), that the model calls itself during the ReAct
loop. This tool was waiting for the loop (A1), which landed in `main` on
2026-10-14 (PRs #12 and #13). It still needs to be registered in the CLI.

Two constraints:
- **The index does not exist at startup.** The CLI only opens it on the
  first question (ADR-0009, decision 5), so as not to force indexing on
  someone who only types commands. Yet the tool is registered at startup.
- **The gateway cuts a tool off after 120 s** (`tool_timeout_s`, ADR-0006).
  The first indexing of the repository (134 files) took 4 min 30 during the
  real trial run of 2026-10-13, on the RunPod pod.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| A. Index at startup, then register the tool with the index | Simplest to understand | Goes back on ADR-0009: several minutes of waiting on a new project, even to type `/profile` |
| B. The tool indexes by itself on the first call | Instant startup | The first indexing exceeds the gateway's 120 s: the call fails, and indexing continues in the background at the same time as the CLI's, on the same database |
| **C. The tool reuses the index the CLI opens on the first question** (chosen) | Instant startup. The CLI already indexes before handing over to the agent: the tool never indexes, so never times out. The least code | The tool depends on the CLI to receive its index: another interface (the web, Workstream D) will have to do the same |

## Decision
`RagTool` is registered at startup **without an index**. On the first
question, the CLI opens the index (as today), then hands it to the tool,
before calling the agent. With `--no-rag`, the tool is not registered: the
agent does not see it. The tool declares the `read` risk.

Its responses have their own presentation ("Search "…": n passages"),
without the instruction attached to automatically added passages, which
says they may be off-topic. It follows `--rag-min-score`, but not
`--rag-top-k`: that setting limits what is added to each question, and the
tool always returns up to 5 passages. Both points come from the real trial
run of 2026-10-14: with `--rag-top-k 1`, the tool only returned the README
passage, and the model answered `qwen3:8b` instead of `bge-m3`.

## Consequences
- ✅ Startup stays instant, and the agent can search the project as many
  times as it wants, in its own words.
- ✅ A single indexing, done in the same place as today: no concurrent
  access to the database.
- ✅ With the `read` risk, the gateway allows it without confirmation, like
  `read_file`. Without a declared risk, it treated it as an execution and
  would have asked for confirmation on every search.
- ❌ If indexing fails (Ollama or `bge-m3` unavailable), the CLI disables
  search for the session: the tool remains visible to the agent but answers
  "Search unavailable". The model must then continue without it.
- ❌ Every interface that uses the agent will have to hand the index to the
  tool: to flag to Workstream D for the web.
- ❌ The first question on a new project remains slow (indexing), as with R1
  today.
- ❌ The model does not always call the tool: when the automatically added
  passages are enough, it answers directly (observed during the real trial
  run). This is intended, but the demo needs a question that goes beyond
  them.
- Follow-up: CLI tests (the tool receives the index, it is not offered with
  `--no-rag`, it ignores `--rag-top-k`) and tool tests (`read` risk, its own
  presentation). Real trial run on the pod on 2026-10-14: the model called
  `search_codebase` on its own, without any confirmation requested.
