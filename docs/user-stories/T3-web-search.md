# User stories - [T3] Web search

Interface: `frontend/`. The tool
itself (`tools/web_search_tool.py`) and its isolated browser
(`execution/sandbox/browser_sandbox.py`) have their stories in US-T3-5 and
US-T3-6 below (numbered US-T2-3 and US-T2-4 until 2026-11-02).
All the stories of T3 are in this file.

Persona: Camille, the developer of the scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)), who picks up
a Python project and wants to follow, correct and keep track of what the agent
does. Traceability: [traceability.md](../design/traceability.md).

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

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: isolated web search: ✅ `python.org` with both models (11 min 16 on CPU, 10 s on GPU).

## US-T3-1 - Check the cited web sources
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ◐ Partly. The `web_search` tool is real on the server side, but the server does not send `web_results` yet: the pages consulted appear in the step's observation, not in the Sources tab. Not tried in the browser yet.
>
> **Update on 2026-11-01:** ✅ The server reads the results back from the tool's answer and sends `web_results`; the interface keeps only http(s) links. Tested, not yet seen in the browser with the real model.

**As** Camille, the developer looking for recent information,
**I want** to see the web pages consulted and be able to open them,
**so that** I can check for myself.

**Acceptance criteria:**
- The Sources tab lists the titles and addresses of the results.
- Links open in a new tab, without passing on the origin page (`noopener`).
- In the demo, no network request is made: the results are scripted.

## US-T3-2 - Not rely on information from memory
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ⏳ Not checked yet: it depends on the model's answer.

**As** Camille, the developer who needs an up-to-date version number,
**I want** the agent to point me to the sources rather than quote a version number from memory,
**so that** I do not use outdated information.

**Acceptance criteria:**
- The answer refers to the sources found and does not state an unchecked version number.

---

## US-T3-3 - Get dated, numbered web results the agent can cite
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, who asks "what is the latest version of pytest?" during the invoice-report fix,
**I want** the agent to search the web and get a short numbered list of results with their address and the search date,
**so that** it can point me to the page it relied on, and does not take a recent result for an error.

**Acceptance criteria:**
- `web_search` returns at most 10 results, each numbered with its title, its URL and its snippet, under a line "Results for: <query> (searched on <date>)".
- A search with no result says "No results for: <query>"; it is not an error.
- A failure (timeout, empty page, captcha) is returned to the model as a readable error with its code (`Timeout`, `SearchEmptyPage`…); the turn goes on.
- By default a search does not ask for confirmation (it reads, it does not change the machine).

## US-T3-4 - Keep control over what web pages can make the agent do
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who configures CodeSensai for the team,
**I want** to make web search ask for confirmation, or to require a confirmation for any later search once untrusted results have been read, and to have hostile text in results cleaned and secrets masked,
**so that** a page that says "search for <secret>" cannot drive the agent without someone saying yes.

**Acceptance criteria:**
- With the `web_search` mode set to `ask`, a search only runs after a "yes"; a refusal starts no container.
- With `confirm_after_untrusted`, the second search of a conversation asks for confirmation.
- Invisible characters are removed from the results and injection markers are logged; keys and e-mail addresses in results are masked.
- Invalid arguments (wrong type, unknown field) and an empty query never start a browser.


---

## US-T3-5 - Search the web for recent information without exposing the agent
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer asking about a recent version of a library,
**I want** the agent to be able to search the web and cite its sources,
**so that** I get an up-to-date answer without the web page being able to attack my machine.

**Acceptance criteria:**
- `web_search` with `python asyncio` returns up to 10 results (title, external URL, snippet); links internal to the search engine are discarded.
- The search runs in a disposable Chromium container that can only reach the search engines (`html.duckduckgo.com`, then `www.bing.com` as a fallback, ADR-0040); no result page is opened.
- The results are untrusted text: they go through the gateway's cleaning and are presented to the model as data, not as instructions.
- An empty query, one longer than 400 characters or one with control characters is refused before any container is started.

## US-T3-6 - Understand why a search fails
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose search returns nothing,
**I want** a message that tells apart an anti-bot block, an empty page, a real network problem and an unexpected page,
**so that** I know whether to try again, change network or fix the configuration.

**Acceptance criteria:**
- A captcha page gives `SearchBlocked`; an empty dump gives `SearchEmptyPage`; a Chromium network error page gives `SearchUnavailable`.
- Any other page that is not a result page gives `SearchUnexpectedPage`.
- A valid query with no result returns "No results"; this is not an error.
- If the `sensai-browser` image is not built, the `ImageMissing` error gives the `docker build` command to run.


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-T3-1 | ✅ | `web/runtime.py` (`_WEB_RESULT`, emits `web_results` after a successful `web_search`), `frontend/src/engine/wire.ts`, `frontend/src/features/chat/SourcesPanel.tsx` (`noopener`) | `tests/web/test_real_features.py::test_web_search_results_are_parsed_for_the_sources_tab`, `frontend/tests/wire.test.ts` (http(s) links only) | Fixed on 2026-11-01: the server now sends `web_results`. Not yet seen in the browser with the real model |
| US-T3-2 | ◐ | `tools/web_search_tool.py` (the description asks the model to trust the results' date) | none | Whether the answer cites sources instead of a remembered version depends on the model; no automated test |
| US-T3-3 Dated results (new) | ✅ | `tools/web_search_tool.py`, `registry.py` | `tests/tools/test_web_search_tool.py` (`test_search_returns_numbered_results_for_the_model`, `test_no_results_is_said_plainly`, `test_failure_tells_the_model_what_happened`, `test_runs_without_confirmation_by_default`), `tests/test_registry.py` |  |
| US-T3-4 Control (new) | ✅ | `tools/web_search_tool.py`, `execution/gateway.py`, `execution/tool_policy.py` | `tests/tools/test_web_search_tool.py` (`test_preference_can_make_it_ask`, `test_after_a_search_the_next_search_asks_when_the_option_is_on`, `test_hostile_result_text_is_cleaned_and_flagged`, `test_secrets_in_results_are_masked_when_the_filter_is_plugged_in`, `test_empty_query_is_reported_without_a_container`) |  |
| US-T3-5 | ✅ | `execution/sandbox/browser_sandbox.py`, `tools/web_search_tool.py` | `tests/execution/sandbox/test_browser_sandbox.py`, `tests/tools/test_web_search_tool.py` (`test_hostile_result_text_is_cleaned_and_flagged`, `test_invalid_arguments_never_start_a_browser`) | Moved from T2 on 2026-11-02 (was US-T2-3) |
| US-T3-6 | ✅ | `execution/sandbox/browser_sandbox.py`, `execution/sandbox/search_parsing.py` | `tests/execution/sandbox/test_browser_sandbox.py` (`SearchBlocked`, `SearchEmptyPage`, `SearchUnexpectedPage`, `ImageMissing`), `tests/execution/sandbox/test_search_parsing.py` | Moved from T2 on 2026-11-02 (was US-T2-4) |
