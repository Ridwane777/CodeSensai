# Real-model trials — [M1] Session persistence & profiles

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: resume a session and recall a word: ✅ with both models, qwen3:8b on CPU 20 min 33 (2 turns), qwen3-coder:30b on GPU 16 s. Earlier measurements below.

This document records the M1 checks run with real models, on top of the
automated tests (`tests/knowledge/test_memory.py`,
`tests/test_cli_persistence.py`). Decision: [ADR-0007](../decisions/0007-session-persistence.md).

## Scenario

```
1. sensai                          /remember answer in French and use pytest
                                   I'm working on a login bug: test_login fails
                                   with a KeyError on "token".
                                   exit
2. sensai                          (resume expected)  Do you remember my bug?
                                   Which test was failing, and with which error?
3. sensai --new-session            Write a test for a function add(a, b).
```

What is checked: the session is resumed, the model actually uses the history,
and the profile applies in a fresh session.

## Results

| Date | Model (machine) | Resume | "Do you remember my bug?" | "Which test, which error?" | Profile in a new session |
|---|---|---|---|---|---|
| 2026-10-11 | `llama3` (dev machine, CPU) | ✅ "resumed (2 messages)" | ❌ "I have no memory" | — | ✅ pytest, in French |
| 2026-10-11 | `granite3.1-moe` (dev machine, CPU) | ✅ | ✅ cites the test and the KeyError | ⚠️ answers with an action plan | ✅ pytest, in French |
| 2026-10-12 | `qwen3-coder:30b` (RunPod pod, GPU), M1 at commit `9a9724e`, RAG disabled | ✅ | ⚠️ "I can't remember the details… but I can help you with the `KeyError` on "token"" | ✅ "`test_login` was failing with a `KeyError` on "token"" | ✅ pytest-style test |
| 2026-10-12 | `qwen3-coder:30b` (RunPod pod, GPU), with the resume instruction | ✅ | ✅ "Yes, you had a login bug where the test failed with a `KeyError` on "token"…" | ✅ same exact answer | — (in a new session, same question: asks for details, does not invent) |

During the 2026-10-12 trial, `/sessions` listed both project sessions with
title, date and message count, and both `sessions.db` and `profile.json` were
created with mode `600`.

## What the trials changed

**The "I have no memory" reflex.** It shows up on `llama3` and also on the
demo model: `qwen3-coder:30b` denied remembering in the very sentence where it
quoted the bug from the previous session. Yet the history was sent (the test
`test_history_kept_after_restart` checks what the model receives). Fix:
when a session is resumed, an instruction read from
`prompts/memory_prompt.txt` (since A4: `prompts/memory/v1.txt`) is appended to
the system prompt ("the following messages really happened […] do not say you
have no memory"). It is not sent in a fresh session, where it would be false;
the test `test_resume_instruction_only_for_resumed_session` checks this.

## Limits

- One scenario, one run per model: these trials show the mechanism works, not
  a success rate.
- Error cases (corrupted database, full disk, failed turn not saved), file
  permissions and the 30-day purge are only checked by the automated tests.
- `/sessions` shows dates in UTC, not local time.
