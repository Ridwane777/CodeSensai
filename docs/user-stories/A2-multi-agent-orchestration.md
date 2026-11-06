# User stories — [A2] Multi-Agent Orchestration

Decisions:
[ADR-0037](../decisions/0037-delegation-sous-agent-outil.md) (delegation through
a tool) and [ADR-0038](../decisions/0038-agents-specialises-et-relais.md)
(specialised agents and relays, proposed).

What the subject asks for: *several specialised agents that coordinate on
a task by passing the work along* (examples given: a researcher, a writer
and a critic in CrewAI; agents that debate to refine an answer in AutoGen;
a router that sends each request to the right agent).

CodeSensei scenario: Camille gives a task that can be split (analysing
several files) or that needs several skills (understanding the code,
changing it, checking the change), and wants the agent to organise itself
rather than handle everything in a single line of reasoning.

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/essais/essai-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: `team_task` on `moyenne([])`: qwen3:8b ❌ (the team did not finish, even with 30 min); qwen3-coder:30b ❌ 0 of 4 with RAG off (the agent did not find `stats.py`, backlog #25), ✅ 3 of 3 with RAG on (64–73 s, project tests pass); with RAG off after `list_files` (ADR-0059): 0 of 3, blocked by the trial script's confirmations typed in advance (once the agent proposed the right change to `stats.py` and the script refused it). A run by hand found two bugs, fixed the same day (backlog #27): a team that wrote nothing was "validé" because the unchanged project's tests passed, and the explorer had no `list_files`.

## US-A2-1 — Split a task into delegated sub-tasks
> **Update on 2026-11-06:** scenario step **S6**, a wider change, handed to the team ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer giving the agent a composite task,
**I want** it to delegate each sub-task to a sub-agent that reasons on its
own and calls its own tools,
**so that** I get one answer per sub-task rather than a single line of
reasoning that mixes everything.

**Acceptance criteria:**
- When the request names three files or more (or a whole folder), the agent
  calls `delegate_task` on its own, once per file; for a simple question or
  one or two files, it does not delegate.
- On explicit request ("délègue à un sous-agent…"), it delegates.
- The sub-agent receives the project prompt (profile, SENSAI.md, remembered
  facts): it answers in the profile's language and knows the remembered facts.
- The sub-agent goes through the same gateway as the main agent: same
  safeguards, same confirmation before a risky action (A3).
- Its answer comes back to the main agent as a normal tool result.

> **Status on 2026-10-24:** ◐ Partly. Spontaneous delegation from three files: 6 out of 8; wrongful delegation: 2 out of 12; on explicit request: 6 out of 6. Project prompt: remembered fact 3/3, profile 2/3. Same confirmations: tested. Measurements: [A2-orchestration.md](../performance/A2-orchestration.md).
>
> **Status on 2026-10-29:** ◐ Partly, web interface only: when a `delegate_task` sub-agent actually starts, the web interface now shows a real relay chip (its role, or "Sous-agent") and the return to the main agent ([ADR-0047](../decisions/0047-real-agent-handoffs-in-the-web.md), proposed). A delegation refused at the confirmation shows no relay. Checked by `tests/web/test_handoffs.py` with a scripted model, not yet with the real model. The sub-agent's own steps are not streamed to the browser.

> **Update on 2026-10-29:** ◐ Web interface ([ADR-0050](../decisions/0050-real-web-features-on-demand-evaluation.md), proposed): the sub-agent's own tool runs are now streamed as `subagent_step` events (`delegate_task` and every `team_task` role) and shown in the reasoning steps as "role › tool"; their output is already filtered by the gateway and cut at 600 characters. Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): `delegate_task` with the explorer role streamed the relays `main → explorateur → main` and the sub-agent's `subagent_step` events.

## US-A2-2 — Not loop forever nor work behind the user's back
> **Update on 2026-11-06:** scenario step **S6**, a wider change, handed to the team ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who wants neither a delegation loop nor ghost work,
**I want** a sub-agent to be unable to delegate again and to stop at its
deadline,
**so that** I keep a responsive session, with no action after the fact.

**Acceptance criteria:**
- A sub-agent does not see the delegation tools; if it still tries to call
  them, it gets an explicit refusal.
- At its deadline, the sub-agent stops: its partial answer comes back to
  the main agent, no tool runs after the deadline and no confirmation is
  asked after the fact.
- A sub-agent that fails (model error, Ollama outage) returns an explicit
  failure message rather than an exception that would interrupt the
  session.

> **Status on 2026-10-24:** ✅ Checked on the pod: 0 re-delegation (tool hidden), stop at the deadline with no tool or confirmation afterwards, partial answer returned; sub-agent failure rendered as a message (tested).

## US-A2-3 — Specialised agents, each with its own tools
> **Update on 2026-11-06:** scenario step **S6**, a wider change, handed to the team ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer handing a task to several agents,
**I want** each agent to have a role (explorer, developer, reviewer) with
its own instructions and only that role's tools,
**so that** no agent does what is not its job (an explorer or a reviewer
never modifies a file).

**Acceptance criteria:**
- `delegate_task` accepts a role; the sub-agent then receives that role's
  instructions and sees only its tools.
- The explorer and the reviewer see neither `write_file` nor `run_code`; a
  call to a tool outside their role is refused without being run.
- The developer can write, with the usual confirmation.

> **Status on 2026-10-24:** ✅ Checked on the pod: out of 10 write requests made to an explorer or a reviewer, 0 file created and 0 confirmation. Yet the model once claimed it had created the file: what it says is not proof.

## US-A2-4 — Work passes from one agent to the next, with a critique
> **Update on 2026-11-06:** scenario step **S6**, a wider change, handed to the team ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer asking for a code change,
**I want** the explorer to gather the context, the developer to produce the
change and the reviewer to critique it, with a return to the developer if
the reviewer finds a defect,
**so that** I get a checked change rather than a first draft.

**Acceptance criteria:**
- `team_task` chains explorer → developer → reviewer; each agent receives
  the previous one's work.
- If the reviewer answers "À CORRIGER", the work goes back to the developer
  with the critique, at most once, then back to the reviewer.
- Each relay is shown in the terminal during the work, and the final result
  sums up the path followed and the reviewer's verdict.
- The whole chain fits within one tool's time limit (120 s by default): if
  time runs out, it stops and says at which step.

> **Status on 2026-10-24:** ✅ Checked on the pod: final code correct 9 times out of 9 (run), path explorer → developer → reviewer; the reviewer, which receives the content actually written, spots wrong work 6 times out of 6 (0 out of 6 with the report alone). Handed to the team for 20 change requests out of 20, never for a question (0 out of 12). The correction loop was not triggered on the pod (tasks succeeded the first time): it is covered by the tests. A change by the team takes 38 to 65 s.
>
> **Status on 2026-10-29:** ◐ Partly, for the web interface (the criteria above speak of the terminal): each `team_task` relay (explorateur → developpeur → relecteur, send-backs included) is now shown as a real relay chip in the conversation and on the Agents page, labelled Explorateur, Développeur, Relecteur ([ADR-0047](../decisions/0047-real-agent-handoffs-in-the-web.md), proposed). Checked by `tests/web/test_handoffs.py` with a scripted model, not yet with the real model. The "Agent actif" selector still only changes the displayed name.

> **Update on 2026-11-02 (US-A2-4):** when the project has tests (`tests/` or `test_*.py`), the **project's tests** give the verdict instead of the reviewer: `pytest -q -x` runs in the project; failing, the work goes back to the developer with the test output; passing, it is validated ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 3; `tools/project_tests.py`; `tests/tools/test_team_tool.py`). Without tests the reviewer keeps its role. Seen with `qwen3-coder:30b` on 2026-11-02 ([trial](../performance/essais/essai-2026-11-02.md), S6) and on 2026-11-03 in both cases ([trial](../performance/essais/essai-2026-11-03.md)): passing tests gave "validé", a change that broke a test gave "à corriger".

> **Update on 2026-10-29 (US-A2-4, web):** ◐ each `team_task` role's tool runs also appear as `subagent_step` steps ("explorateur › read_file"…). Tested (`tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx`), not yet with the real model. The "Agent actif" selector and the Agents page profiles are still demo data.

> **Update on 2026-11-01:** ◐ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): every `team_task` relay (explorer → developer → reviewer → main) and step was streamed, but the developer wrote a new `src/sensai/stats.py` instead of editing `stats.py` and the reviewer validated it (finding 2, not fixed).


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-A2-1 | ◐ | `tools/delegate_tool.py` | `tests/tools/test_delegate_tool.py` | The tool works; spontaneous delegation depends on the model (6/8 measured, 2/12 wrongful) |
| US-A2-2 | ✅ | `tools/delegate_tool.py` | `tests/tools/test_delegate_tool.py` (`un_sous_agent_ne_redelegue_pas`, `apres_l_echeance_le_sous_agent_est_arrete_avec_sa_reponse_partielle`, `profondeur_de_delegation_est_bornee`) |  |
| US-A2-3 | ✅ | `tools/delegate_tool.py`, `tools/team_tool.py` | `tests/tools/test_delegate_tool.py`, `tests/test_cli_persona.py::test_delegate_task_refuse_un_outil_desactive_par_la_persona` |  |
| US-A2-4 | ✅ | `tools/team_tool.py` | `tests/tools/test_team_tool.py` (`le_travail_passe_de_l_explorateur_au_developpeur_puis_au_relecteur`, `a_corriger_renvoie_au_developpeur_avec_la_critique_une_seule_fois`) |  |
