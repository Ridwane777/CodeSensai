# User stories — [X4] Questions and forms

Interface: `frontend/`.

CodeSensei scenario: Camille takes over a Python project and wants to
follow, correct and keep track of what the agent does, without reading the code.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-interface-web-simulee.md)).
On 2026-10-18 the interface was wired to the real agent by `sensai-web`
([ADR-0035](../decisions/0035-serveur-web-reel.md)) and tried in a browser with
`qwen3-coder:30b` ([web-reel.md](../performance/web-reel.md)). On 2026-10-29 the
agent got an `ask_user` tool ([ADR-0046](../decisions/0046-ask-user-tool.md)).
Each story carries its status:
✅ checked with the real agent · ◐ partly · 🎭 still simulated · ⏳ not checked yet.
Detail per feature: [simule-vs-reel.md](../architecture/web/simule-vs-reel.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories of the interface: [README.md](README.md).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `ask_user` form answered through `/answer`: ✅ with both models (8 min 57 on CPU, 8 s on GPU).

## US-X4-1 — Answer the agent without leaving the chat
> **Update on 2026-11-06:** scenario step **S5**, a missing piece of information ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ The real server now sends the agent's questions
> (`ask_user`, ADR-0046) and returns the answers to the model. Checked through
> the real server with a scripted model (`tests/web/test_questions.py`) and in
> the frontend tests; not yet tried with `qwen3-coder:30b`.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): the `question` event was answered through the API and in the page's form card, and the agent repeated the values; left unanswered, the card expired after 100 s and the agent said what was missing instead of guessing.

**As** Camille, the developer the agent is missing a piece of information from,
**I want** to answer its questions in a form built into the conversation,
**so that** I don't have to retype them as free text.

**Acceptance criteria:**
- The question appears as a card with one field per piece of information (choice, text, checkbox).
- Sending is blocked while a required text field is empty.
- The agent takes over again using the values entered in its answer.
- Once sent, the form becomes a read-only summary.
- An invalid answer is refused by the server and the question stays open; no
  answer within 100 s, an interruption or a closed tab ends the wait, and the
  agent says it is missing the information instead of guessing it.

## US-X4-2 — Decide before an irreversible action takes place
> **Update on 2026-11-06:** scenario step **S5**, a missing piece of information ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ✅ Checked with the real agent: the card shows the action, its detail and its risk; "Allow" creates the file ("✓ Allowed"); "Refuse" creates nothing ("✕ Refused") and the agent says so. Also covered by the server tests (yes, no, timeout, late answer).

**As** Camille, the developer who stays in control of her project,
**I want** to allow or refuse with a button a risky action proposed by the agent,
**so that** no deletion takes place without my agreement.

**Acceptance criteria:**
- The card states the action, its detail and its risk level.
- "Allow" runs the action; "Refuse" cancels it and the agent confirms it touched nothing.
- After the decision, the buttons disappear and the decision stays displayed.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-X4-1 | ✅ | `tools/ask_user_tool.py`, `web/questions.py` | `tests/tools/test_ask_user_tool.py`, `tests/web/test_questions.py` |  |
| US-X4-2 | ✅ | `execution/web_confirmation.py` | `tests/web/test_web_facade_spike.py` (`test_l_outil_a_risque_ne_s_execute_qu_apres_accord`, `test_refus_n_execute_rien_et_le_tour_continue`) |  |
