# A1 — Reasoning loop (ReAct)

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)).

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: read `stats.py` and explain `moyenne`: qwen3:8b on the laptop CPU ✅ (8 min 26); qwen3-coder:30b on a GPU ✅ (file read and right answer; the first run was marked failed by the script's check, then 3 of 3 once fixed, 5–7 s).

## User Story 1: Debug a failing test by exploring the code
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, the developer who took over an unfamiliar code base**, I want the agent to **explore the project, read the code and the error traces to find the root cause**, so that **I can fix the bug without reading every file by hand**.

### Acceptance criteria

- The agent calls tools (search, file read) with no human action between calls
- The agent receives each tool's result and adjusts its strategy (if the search finds nothing, it tries another query)
- The agent stops when it has a final answer and does not loop forever
- The answer includes the cause of the bug and a suggested fix

## User Story 2: Generate code from a vague requirement
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

As **Camille, handed a vague requirement by her lead**, I want the agent to **clarify an imprecise requirement by asking questions, look for similar examples, then generate the code**, so that **I can start developing without a clarification meeting**.

### Acceptance criteria

- The agent asks for details if the requirement lacks precision
- The agent looks for existing code or similar patterns in the project
- The agent generates a working prototype based on what it learnt
- The generated code follows the project's conventions (detected while exploring)
- The agent proposes unit tests to check the behaviour

---

## US-A1-3 — Choose how long the agent may search before it stops
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Update on 2026-11-01:** ✅ checked with the real agent.

**As** Camille, the developer whose agent sometimes needs more than a few steps to find a bug,
**I want** to set the maximum number of model calls per turn in `config.json` or on the command line,
**so that** a long investigation is not cut short, and a runaway loop still stops and tells me so.

**Acceptance criteria:**
- `max_iterations` in `config.json` (or `--max-iterations`) sets the limit; the default is 6; a value outside 1 to 50 is refused at start-up.
- When the limit is reached without a final answer, the turn ends with `max_iterations` and the CLI says "[Stopped] Maximum number of steps reached without a final answer." instead of showing an empty answer.
- The same setting applies in `sensai-web` and in scheduled tasks.

## US-A1-4 — A tool call written as text is not silently lost
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Update on 2026-11-01:** ✅ checked with the real agent.

**As** Camille, whose local model sometimes writes its tool call as text instead of using Ollama's `tool_calls` field,
**I want** the agent to read a call that stands alone in the answer (with the same confirmation as any call), and to ask the model again when a call is mixed with prose,
**so that** the investigation goes on instead of stopping on a piece of XML.

**Acceptance criteria:**
- A reply that is only `<tool_call><function=…>…</function></tool_call>` is executed through the gateway, and a risky tool still asks for confirmation; a refusal applies.
- A tool that was not offered is never executed, and a call in the middle of a text is not executed.
- A reply mixing text and a call makes the model answer again (bounded number of retries); an ordinary answer that mentions XML is not retried.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| Story 1 Debug a failing test | ◐ | `core/agent.py` (`run_agent_turn`) | `tests/core/test_agent.py` (`test_one_tool_call_then_the_final_answer`, `test_the_tool_result_is_sent_back_to_the_model`, `test_the_loop_stops_at_max_iterations`) | The loop criteria (tools without human action, result sent back, bounded stop) are proved. "Tries another query" and "the answer gives the cause and a fix" depend on the model: no automated test |
| Story 2 Code from a vague requirement | ◐ | `tools/ask_user_tool.py`, `tools/rag_tool.py` | `tests/tools/test_ask_user_tool.py`, `tests/tools/test_rag_tool.py` | The tools exist (ask a question, search the project); following the project's conventions and proposing tests is model behaviour, not proved by a test |
| US-A1-3 Step limit (new) | ✅ | `config.py` (`max_iterations`), `core/agent.py`, `cli.py`, `web/runtime.py` | `tests/core/test_agent.py::test_the_step_count_is_configurable`, `tests/core/test_events.py::test_a_stop_at_max_iterations_is_reported`, `tests/test_config.py::test_generation_parameters_defaults_and_overrides`, `tests/test_config.py::test_readers_for_schedule_and_eval`, `tests/scheduling/test_runner.py::test_max_iterations_is_recorded` |  |
| US-A1-4 Text tool calls (new) | ✅ | `core/agent.py` (`_read_textual_calls`) | `tests/core/test_agent.py` (`test_a_lone_call_in_the_answer_is_parsed_and_goes_through_confirmation`, `test_a_tool_not_offered_is_never_executed`, `test_a_call_in_the_middle_of_text_is_not_executed`, `test_the_model_is_retried_if_it_mixes_text_and_call`) |  |
