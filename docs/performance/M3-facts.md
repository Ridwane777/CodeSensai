# Real-model trial - [M3] Fact memory

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `/remember` then `/profile`: ✅ with both set-ups (< 1 s). Earlier measurements below.

M3 check with the real model, on top of the automated tests
(`tests/knowledge/test_facts.py`, `tests/tools/test_fact_tools.py`, and the
M3 tests in `tests/test_cli_rag.py`). Decision:
[ADR-0030](../decisions/0030-structured-fact-memory.md). The trial also led
to [ADR-0031](../decisions/0031-text-written-tool-calls.md) and to a fix for
an M4 regression.

## What is checked
The user stories: the agent stores a fact on its own (US-M3-1), finds it in a
new session and resolves inverse relations (US-M3-2), corrects a value
without keeping the old one, and lets the user delete (US-M3-3).

## Machine and settings
- RunPod pod (Community Cloud, 24 GB GPU), Ollama 0.40.6,
  `qwen3-coder:30b`, context window 32,768. Address kept out of the repo.
- `sensai --no-rag --new-session`, throwaway data folder, small empty
  project; confirmations given by scripted input (`o`).
- 8 tools offered to the model: `run_code`, `read_file`, `write_file`,
  `web_search`, `search_codebase`, `update_state`, `save_fact`, `recall_facts`.

## First trial: what worked and what broke

| Scenario | Result |
| --- | --- |
| "The auth service uses Redis 7, depends on PostgreSQL, Meric owns it. Remember that." | ✅ 3 facts saved, each confirmed (`add` for the dependency, `replace` for the version) |
| New session: "Which Redis version does auth use?" | ✅ `recall_facts`, answers 7 citing the fact |
| "What depends on PostgreSQL?" | ✅ inverse lookup: auth |
| "Which database does billing use?" | ✅ "I have no fact", offers to search the code |
| "We moved to Redis 8, update your memory" | ❌ the call is written **in the text** (`<function=remember_fact>…`), nothing runs, then the model **claims** "the version was changed from 7 to 8" |

## Investigation: tool calls written as text

Measured directly against the Ollama API (structured calls received in
`tool_calls`), same system prompt as the CLI:

| Situation | Result |
| --- | --- |
| "remember that…", only 1 tool offered | 8/8 structured |
| same request, 8 tools offered | 0/8 |
| without our system prompt | same rate as with it: it is not the cause |
| `read_file` with 5 tools (state of `main` on 10/14) | 5/5 |
| `read_file` after adding `update_state` (M4, long description) | **1/5: regression introduced by M4** |
| `update_state` description cut down to one sentence | 5/5 |
| `remember_fact` (12 runs) vs. the name `save_fact` | 4/12 vs. 8/12 |

Conclusions: qwen3-coder drops the opening `<tool_call>` tag more often when
many tools are offered and their descriptions are long (no single sentence is
to blame); the tool name matters too. Fixes:
1. tool descriptions cut to one sentence, usage instructions moved into the
   system prompt (fixes the M4 regression);
2. `remember_fact` renamed `save_fact`;
3. ADR-0031: a call written as text is parsed only if the reply consists
   solely of calls to offered tools, and then goes through the gateway and
   confirmation; otherwise the model is retried twice, then the turn stops
   with an error instead of a false claim.

After the fix, structured calls with all 8 tools (6 runs each):
`read_file` 5/6, `run_code` 6/6, `web_search` 6/6, `search_codebase` 6/6,
`recall_facts` 6/6, `update_state` 6/6, `save_fact` 1/6 (hence ADR-0031).

## Final trial (6 "remember that…" requests, empty memory)

| | Retries only | + text parsing (ADR-0031) | + name consistency |
| --- | --- | --- | --- |
| Facts saved | 2/5 | 6/6 | **6/6** |
| "Redis 8" replaces "Redis 7" | - | ❌ 7 remains, under another name | ✅ replaced (the agent looks up the entry first) |
| Duplicates | - | 3 names for the same data | 1 duplicate, same value |

"Name consistency": spaces, `_` and `-` are equivalent; the confirmation and
the `save_fact` reply show the entity's already known attributes; the prompt
asks to look up the entity before saving; a missing attribute returns
everything known about the entity.

New session, "Which Redis version does the auth service use, and on which
port?": **3 runs out of 3** answer "Redis 8, port 8080" with a single
`recall_facts` (before the last fix, the model searched for `redis_version`,
found nothing and dug through non-existent files).

## Limits
- The model picks the names itself: a duplicate is still possible; the
  confirmation shows it to the user, who can refuse.
- Parsing text-written calls depends on qwen3-coder's format (ADR-0031).
- Measured on a single project, with scripted input; one to eight
  repetitions per case: orders of magnitude.
