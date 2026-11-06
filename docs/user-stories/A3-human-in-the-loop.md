# User stories — [A3] Human-in-the-Loop (confirmation before a risky action)

CLI confirmer `execution/human_in_loop.py`, permission
modes `execution/tool_policy.py`, called by the gateway
(`execution/gateway.py`, [ADR-0006](../decisions/0006-passerelle-d-outils.md)).
When these stories were written, button confirmation in the web interface was
still to be done: it provides another "confirmer" without touching the
gateway ([ADR-0005](../decisions/0005-interface-web-facade.md); stories in
[A3-human-in-the-loop.md](A3-human-in-the-loop.md)).

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

---

## US-A3-1 — See the exact plan before code runs
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who lets the agent run code,
**I want** to see the full code and the risk level before it runs,
**so that** I decide knowingly.

**Acceptance criteria:**
- Before `run_code`, the CLI shows the tool, its risk (`execute`), the exact code and the answer timeout.
- Without an answer, the code does not run: the sandbox is never started without an explicit confirmation.
- What I approve is what runs: the text of the request is built from the same arguments as the call.

## US-A3-2 — Refuse without breaking the agent
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who refuses an action,
**I want** the agent to receive a clear refusal and adapt,
**so that** I keep control without restarting the session.

**Acceptance criteria:**
- Only `o`, `oui`, `y`, `yes` (case-insensitive) allow; an empty answer, unknown text, Ctrl-C, closed stdin or CI count as a refusal.
- A refusal sends the agent a readable tool result (action refused by the user); the loop goes on, nothing is executed.
- An expired answer timeout (60 s by default, configurable) is a refusal.

## US-A3-3 — Choose when I am asked, without being able to switch security off
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who finds some confirmations repetitive,
**I want** to set each tool's behaviour in the configuration,
**so that** I am not asked about reads while keeping the confirmation on writes and execution.

**Acceptance criteria:**
- By default, reading and web search go through without a question; writing and executing always ask.
- I can disable a tool (`disabled`) or harden a mode (`ask`, `deny`); I cannot relax `write` or `execute`, even through a config file or a prompt injection.
- A tool that does not declare its risk is treated as `execute`.
- With `confirm_after_untrusted`, after reading untrusted content (web page, file), every tool that is not read-only asks for confirmation again.

---

## Part merged from `A3-web-confirmation.md` on 2026-11-02: User stories — [A3] Human-in-the-Loop, confirmation from the browser

Broker `execution/web_confirmation.py`
(`WebConfirmationBroker`), decision in [ADR-0015](../decisions/0015-confirmation-web-synchrone.md),
HTTP contract in [web-api.md](../architecture/web/web-api.md). Complements the CLI A3 stories.

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../conception/persona-and-scenario.md)).

---

## US-A3-W1 — Allow a risky action with one click in the browser
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who uses CodeSensei in the browser,
**I want** to see what the agent wants to run (tool, risk, exact plan) and click "Autoriser" or "Refuser",
**so that** I keep control over every risky action without going through a terminal.

**Acceptance criteria:**
- Before a risky action, the stream receives a `confirm_request` event with `id`, `tool`, `risk`, `summary`, `arguments` and `timeout_s`.
- As long as I have not answered, the tool does not run.
- If I allow, the tool runs once and the stream continues with its result.
- If I refuse, the tool does not run, the stream continues and the agent explains or proposes an alternative.

## US-A3-W2 — Silence or an error never counts as approval
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who steps away or whose tab closes,
**I want** any lack of a clear answer to be a refusal,
**so that** I never find code executed that I did not approve.

**Acceptance criteria:**
- Without an answer before `timeout_s`, the action is refused and the tool is not started.
- If the browser disconnects, the pending request is refused at once, and so are the next ones, without a new question.
- Only the JSON boolean `true` allows: `false`, `1`, `"true"`, `null` or a missing field are refusals.
- If sending the question to the browser fails, the action is refused.

## US-A3-W3 — Be told when my answer is no longer valid
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who clicks after the timeout, or twice,
**I want** the interface to tell me the request no longer exists, with no side effect,
**so that** I do not believe I allowed an action that was already refused.

**Acceptance criteria:**
- Answering with an unknown, expired or already used id returns 404 and changes nothing.
- When I answer twice, the first answer wins.
- A late answer never starts the tool.

## US-A3-W4 — Keep several requests independent
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who opens several sessions,
**I want** each confirmation request to have its own id and timeout,
**so that** allowing one action does not allow another.

**Acceptance criteria:**
- Two simultaneous requests get two different ids.
- Answering one does not wake the other.
- After each answer, refusal or timeout, no request is left pending.

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-A3-1 | ✅ | `execution/human_in_loop.py`, `execution/gateway.py` | `tests/execution/test_human_in_loop.py` (`test_user_sees_the_exact_plan`, `test_run_code_does_not_start_without_yes_through_gateway`) |  |
| US-A3-2 | ✅ | `execution/human_in_loop.py` | `tests/execution/test_human_in_loop.py` (`test_anything_else_refuses`, `test_closed_input_or_interrupt_refuses`), `tests/execution/test_gateway.py::test_refusal_is_a_result_the_agent_can_read` |  |
| US-A3-3 | ✅ | `execution/tool_policy.py` | `tests/execution/test_tool_policy.py` (`test_default_modes`, `test_preferences_cannot_loosen_write_or_execute`, `test_missing_or_invalid_risk_is_treated_as_execute`), `tests/tools/test_web_search_tool.py::test_after_a_search_the_next_search_asks_when_the_option_is_on` |  |
| US-A3-W1 | ✅ | `execution/web_confirmation.py` | `tests/execution/test_web_confirmation.py` (`test_emitted_payload_is_exactly_the_documented_one`, `test_gateway_approve_runs_the_tool_once`, `test_gateway_refusal_does_not_run_the_tool_and_is_not_an_exception`) |  |
| US-A3-W2 | ✅ | `execution/web_confirmation.py` | `tests/execution/test_web_confirmation.py` (`test_timeout_refuses_and_leaves_nothing_pending`, `test_anything_but_literal_true_refuses`, `test_emit_raising_refuses_and_cleans_up`, `test_requests_after_close_refuse_immediately_without_emit`) |  |
| US-A3-W3 | ✅ | `execution/web_confirmation.py`, `web/server.py` | `tests/execution/test_web_confirmation.py` (`test_duplicate_answer_first_one_wins`, `test_late_answer_after_timeout_is_ignored`), `tests/web/test_web_facade_spike.py::test_une_confirmation_inconnue_est_sans_effet` |  |
| US-A3-W4 | ✅ | `execution/web_confirmation.py` | `tests/execution/test_web_confirmation.py::test_two_concurrent_requests_are_independent`, `tests/web/test_web_facade_spike.py::test_deux_sessions_en_parallele_ne_melangent_pas_leurs_confirmations` |  |
