# ADR-0059 — A read-only `list_files` tool so the agent can see the project

- **Status**: Proposed
- **Date**: 2026-11-06
- **Deciders**: Ridwane (Lot C), to be accepted by the team
- **Lot concerned**: B (tools, T4); all interfaces get it through `build_registry`

## Context

In the [trial of 2026-11-06](../performance/trials/trial-2026-11-06.md), T5
(`/structured`) and A2 (`team_task`) failed with **both** models when RAG was
off: the agent had no way to know which files the project holds. It tried
`main.py`, `src/utils.py`, `calculs.py`… until the 6-step limit, asked the user
where the code was, or wrote a new `src/moyenne.py` next to the real
`stats.py`. With RAG on, A2 passed 3 of 3; but RAG is optional on purpose: it
needs `bge-m3` (1.2 GB) and minutes of indexing on a laptop
([persona-and-scenario.md](../design/persona-and-scenario.md)). Backlog #25.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| **A read-only `list_files` tool** | Fixes the cause: the agent looks before it reads; no model, no index; reuses `FilePermissions` and the RAG walk; what Claude Code, Cursor or Aider do | One more tool described in every prompt (tokens); a cap to choose |
| The file list in the system prompt | Nothing for the model to decide | Tokens on every turn (heavy for `qwen3:8b` on CPU, ~10 tokens/s to read the prompt); stale as soon as the agent creates a file; does not scale to a large project |
| Make RAG mandatory | No new tool | `bge-m3` and indexing become required; RAG answers "where is X", not "which files exist" |
| Let `run_code` list the files | No new tool | The sandbox does not see the project, and each call asks for confirmation |

## Decision

Add `list_files` (`tools/list_files_tool.py`), registered in `build_registry`
next to `read_file`, so the CLI, the web server and the scheduler all get it.
It is read-only (`risk = "read"`, no confirmation), lists the project or one
of its folders one path per line, applies `FilePermissions.check_read` to the
folder and to each file (protected names such as `.env` are not even named),
follows the RAG walk (`git ls-files`, so `.gitignore`; dependency and cache
folders skipped), and stops at 200 paths with a message asking for a
sub-folder.

## Consequences

- ✅ Without RAG, the agent can find `stats.py` in one step instead of
  guessing; T5 and A2 can be rerun with RAG off to check it.
- ✅ Same rules as `read_file`: nothing outside the allowed folders, no
  secrets, and it goes through the gateway (guardrails, journal).
- ❌ One more tool in every request's `tools` list: a few hundred tokens,
  which a small model on CPU pays on every turn.
- ❌ The 200-path cap is a guess, not a measurement; on a large project the
  model must call it again on sub-folders.
- ❌ It reuses two private helpers of `knowledge/rag.py` (`_git_files`,
  `_walk_files`): a change there changes both.
- Measured after the change (pod, `qwen3-coder:30b`, RAG off): T5 3 of 3,
  `list_files` then `read_file stats.py` (10–12 s), against 0 of 4 before. A2
  could not be judged: the trial script's confirmations, typed in advance,
  refused the agent's writes.
- Follow-up: tests in `tests/tools/test_list_files_tool.py`; judge A2 with RAG
  off with confirmations answered as they come; revisit the cap if a real
  project hits it.
