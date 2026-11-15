# User stories - [X2] Branches: resume and interrupt

Interface: `frontend/`.

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)), who picks up
a Python project and wants to follow, correct and keep track of what the agent
does.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-simulated-web-interface.md)).
On 2026-10-18 the interface was plugged into the real agent through `sensai-web`
([ADR-0035](../decisions/0035-real-web-server.md)) and tried in a browser
with `qwen3-coder:30b` ([real-web.md](../performance/real-web.md)). Each story
carries its status:
✅ checked with the real agent · ◐ partly · 🎭 still simulated · ⏳ not checked yet.
Detail per function: [simulated-vs-real.md](../architecture/web/simulated-vs-real.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories of the interface: [README.md](README.md).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: fork after the first message: ✅ with both set-ups.

## US-X2-1 - Resume from an edited message without losing the original
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ✅ Checked with the real agent: "Modifier" then "Envoyer la variante" creates "Variante 1", which is a new session on the server side with its own answer. Going back to the main branch is covered by the engine's tests (`httpEngine.test.ts`), without having been clicked.

**As** Camille, the developer who phrased a request badly,
**I want** to edit one of my messages and get a new answer,
**so that** I can explore another direction without erasing the first one.

**Acceptance criteria:**
- Each sent message offers "Modifier".
- Sending the variant creates a branch and shows the new answer.
- The version selector lets me go back to the main branch, which finds its history intact.
- An empty edited message is not sent.

## US-X2-2 - Interrupt and redirect the agent
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ◐ Partly. "Stop" is checked: "Generation interrupted", no more words arrive. **Not met with the real agent**: a message cannot be sent during a generation, because the server handles one turn at a time (ADR-0022); "Stop" must be clicked first.

**As** Camille, the developer whose agent is heading the wrong way,
**I want** to stop it during the generation, or send it a new instruction without waiting,
**so that** I do not waste time on a useless answer.

**Acceptance criteria:**
- The "Stop" button only appears during a generation.
- After the stop, the partial answer stays visible with the mention "Generation interrupted" and no more words arrive.
- A message sent during a generation interrupts the previous one and then starts the new one.

---

## US-X2-3 - Stop a turn that is going the wrong way
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Update on 2026-11-01:** ✅ checked with the real agent.

**As** Camille, whose agent starts rewriting the wrong file,
**I want** to stop the current turn with "■ Stop" or Escape and then send another instruction,
**so that** nothing else runs and the half answer is not kept as if it were complete.

**Acceptance criteria:**
- "■ Stop" or Escape calls `POST /api/sessions/{id}/interrupt`: no further model call or tool starts and the stream ends with `done` marked interrupted.
- The interrupted turn is not saved in the history; interrupting while a confirmation or a question is pending refuses it.
- Interrupting when no turn runs has no effect; sending a second message while a turn runs is refused with `409`.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-X2-1 | ✅ | `web/server.py` (`/fork`), `frontend/src/pages/Chat.tsx` | `tests/web/test_server.py` (fork test), `frontend/tests/httpEngine.test.ts` |  |
| US-X2-2 | ◐ | `web/server.py` (`/interrupt`) | `tests/web/test_server.py::test_interrupt_without_a_turn_has_no_effect` | "A message sent during a generation interrupts the previous one" is not implemented: the server answers `409` and Stop must be pressed first |
| US-X2-3 Stop a turn (new) | ✅ | `web/server.py`, `web/runtime.py`, `frontend/src/state/useEngine.tsx` | `tests/web/test_web_facade_spike.py` (`test_interrupt_ends_with_done_interrupted_without_saving_the_turn`, `test_one_turn_at_a_time_per_session`), `tests/web/test_server.py` (`test_interrupt_during_a_confirmation`, `test_interrupt_without_a_turn_has_no_effect`), `tests/web/test_questions.py::test_interrupt_during_a_question` |  |
