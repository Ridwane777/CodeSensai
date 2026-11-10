# Real-model trial — [M4] Project state document

> **Latest trial, 2026-11-06** ([report](trials/trial-2026-11-06.md)), qwen3:8b on the team laptop (CPU) and qwen3-coder:30b on a 24 GB GPU pod: `/state`: ✅ with both set-ups (< 1 s). Earlier measurements below.

M4 check with the real model, on top of the automated tests
(`tests/knowledge/test_state_document.py`, `tests/tools/test_state_tool.py`,
and the M4 tests in `tests/test_cli_rag.py`, `tests/core/test_events.py`,
`tests/knowledge/test_rag.py`). Decision:
[ADR-0029](../decisions/0029-project-state-document.md).

## What is checked
The Definition of Done: after several exchanges, the document reflects the
project state **without being corrupted or rewritten in full**. And the user
stories: the agent knows it in a new session (US-M4-1), only the targeted
section changes (US-M4-2), every change is visible, logged and can be undone
(US-M4-3).

## Machine and settings
- RunPod pod (Community Cloud, 24 GB GPU), Ollama 0.40.6,
  `qwen3-coder:30b`, **context window of 32,768 tokens** (read from
  `/api/ps`). Pod address kept out of the repo.
- First call after the pod starts: 74 s (loading into memory).
- `sensai --no-rag --new-session`, throwaway data folder, in a small project:
  `calcul.py` (one typo) and a hand-written `SENSAI.md` with a preamble
  "Hand-written note: do not touch.".
- Confirmations are given by scripted input (`o`).

## Scenario and results (2026-10-17)

| Step | What the agent does | Result |
| --- | --- | --- |
| 1. "Fix the bug in calcul.py, then update the state document" | `read_file`, `write_file`, then `update_state` on "Done" and on "In progress" | ✅ Each confirmation shows the section before and after. `diff` against the original: only "Done" and "In progress" changed; the preamble, "Decisions" and "Known issues" are identical. 20 s for the turn |
| 2. New session: "Where are we? Answer without using a tool." | No tool call | ✅ Accurate summary of the four sections (US-M4-1). 3.5 s including commands |
| 3. `/state history` | — | ✅ Date, action, section and summary of both updates |
| 4. `/state undo En cours`, twice | — | ⚠️ The 1st restores "- Nothing", the 2nd **undoes the undo**. Matches the first version of the ADR, but confusing: fixed (see below) |
| 5. After the fix: "Add a docstring, note it, add In progress: write tests", then `/state undo Fait` twice | `write_file`, `update_state` (`append` on "Done", `replace` on "In progress") | ✅ The agent uses `append` without copying the old line. Both undos remove the last two lines of "Done", like Ctrl+Z |

## What the trial changed
1. **Multi-level undo.** A second undo goes back one more change instead of
   undoing the first undo (ADR-0029 clarified, tests
   `test_two_undos_go_back_two_changes` and
   `test_new_change_after_undo_starts_from_there`).
2. **`append` rather than `replace` for "Done".** In the first trial, the
   model replaced "Done" by copying the old line back: correct, but one slip
   would have deleted a line. The tool description now recommends `append`
   for "Done" and "Decisions"; in the second trial, the model used it.
3. **The diff is shown at confirmation.** The CLI confirmer showed the raw
   arguments instead of the tool's plan: the `write_file` diff was never
   shown. Fixed for both tools.

## Limits
- One measurement per step: orders of magnitude.
- In the second trial, the model also offered to write a test file; the
  scripted input had no "o" left and answered with commands, taken as
  refusals. The refusals were handled correctly (nothing written), but this
  part says nothing about behavior with a real user.
- A single small project: behavior with a `SENSAI.md` close to the
  8,000-character limit is only checked by the tests.
