# CodeSensei — global retrospective

Written on 2026-10-25, with what we know at the end of the project. It looks
at the **whole application**, component by component: what we chose, what
the measurements showed, which concrete alternative would have been better,
from which point it becomes preferable, and what it costs. Figures come from
the repository (`docs/performance/`, ADRs) and from the
[full trial of 2026-10-24](../performance/essais/essai-2026-10-24.md); none is
invented. Where something was not measured, it says so.

## The project in numbers (measured)

The first rows are the snapshot of 2026-10-25; the dated rows below them
update it.

| | |
| --- | --- |
| Duration | 2026-09-22 → 2026-10-24 |
| Team | 4 people, 4 lots (A brain, B hands, C memory, D interface) |
| History | 291 commits, 42 merged PRs at the time of writing |
| Code | 11,530 lines of Python (`src/`), 13,671 lines of tests, 80 TypeScript files |
| Tests | 1,300 passing, 20 expected failures (known EV4 gaps, ADR-0018) |
| Decisions | 41 ADRs |
| Catalogue features | 28 targeted (ADR-0008); not delivered: A5 Persona, A7 Prompt optimisation, M2 Token budgeting |
| Update 2026-11-01 | 1,652 tests passing and 20 expected failures (`pytest -q`); 58 ADRs; A5, A7 and M2 have since been delivered ([user-stories audit](../user-stories/README.md)); scope decision proposed in ADR-0056 |
| Update 2026-11-02 | 1,645 tests passing and 19 expected failures (`pytest -q`); 58 ADRs, ADR-0056 to ADR-0058 accepted; 533 commits, 76 merged PRs; 16,609 lines of Python in `src/`, 15,153 lines of tests, 76 TypeScript files in `frontend/src/`; generation speed measured: 115–119 tok/s for `qwen3-coder:30b` on the pod's GPU, 4.5–4.8 tok/s for `qwen3:8b` on a team laptop without GPU ([generation-parameters.md](../performance/generation-parameters.md)) |

## What we would build differently

### 1. Guardrails: one checkpoint before the model, not one per path

**What we did.** Secrets and personal data are masked by the tool gateway, on
each tool output (ADR-0006, EV2).
**What happened.** The passages that the project search (R1) adds to every
question did not go through the gateway: an API key read from a project file
reached the model in clear, in the CLI and on the web. 1,300 unit tests were
green; only the end-to-end trial found it (fixed in PR #88).
**Alternative.** Filter **everything sent to the model** in one place: the
Ollama client (`core/ollama_client.py`), right before the HTTP request. A new
path to the model (RAG, memory, sub-agents, MCP) is then protected by
construction instead of by discipline.
**When it is preferable.** As soon as more than one component builds the
prompt — which was the case from week 2 (RAG, facts, state document).
**Cost.** One pass of the filter over the whole prompt on every call (regular
expressions; not measured here); risk of masking code that looks like a
secret, already accepted for tool outputs.

### 2. Orchestration: decide in code what can be decided in code

**What we did.** When to delegate and when to hand code to the team is a rule
in the system prompt (`v2`, ADR-0038).
**What happened.** The model follows it most of the time, not always:
spontaneous delegation on 6 of 8 requests that cite three files or more, 2
wrong delegations out of 12; code changes handed to the team 20 out of 20 in
one series, but one miss during the full trial
([A2-orchestration.md](../performance/A2-orchestration.md)).
**Alternative.** A deterministic **router** in front of the agent: count the
file paths in the request (three or more → `delegate_task`), detect a write
request (→ `team_task`), and leave only the ambiguous cases to the model.
**When it is preferable.** When the behaviour must be demonstrable every time
(a demo, a paying customer), or when a wrong choice is expensive (a
delegation costs 37 to 120 s instead of 13 to 33 s).
**Cost.** Rigid on phrasing ("these two modules and their tests"); a rule set
to maintain next to the prompt.

### 3. Tool calling: fewer tools per turn, or constrained decoding

**What we did.** All tools are offered to the model at every turn (10 built-in
tools, plus the MCP tools), through Ollama's native tool calling (ADR-0003).
**What happened.** With 8 tools offered, `qwen3-coder:30b` called `save_fact`
correctly 1 time out of 6; with that single tool offered, 8 out of 8
(ADR-0031). It also writes tool calls as plain text, which forced a fallback
parser (ADR-0031) and triggers EV2 warnings (`forged_tool_markup`).
**Alternatives.**
- **Tool routing**: offer only the tools relevant to the request (a keyword or
  embedding pre-selection), as the measurement suggests.
- **Constrained decoding of tool calls**: serve the model with the
  `llama.cpp` server (GBNF grammars) or vLLM (guided decoding), so a tool call
  cannot be malformed.
**When it is preferable.** Tool routing: as soon as more than a handful of
tools are offered, which is the case. Constrained decoding: if malformed calls
keep appearing with the chosen model.
**Cost.** Routing can hide the right tool; `llama.cpp`/vLLM replace Ollama,
which the subject imposes (ADR-0001) and which is the simplest local install.

### 4. Structured output: one call would need another serving stack

**What we did.** `/structured` first lets the agent search with its tools,
then formats the answer with Ollama's `format` field (ADR-0039), because
`format` and `tools` cannot be combined in one Ollama call.
**What happened.** Right answers went from 0/15 to 15/15, but at the price of
two calls: 3.7 to 15.8 s instead of 0.9 to 3.9 s
([T5-structured.md](../performance/T5-structured.md)).
**Alternative.** A server that accepts tools **and** a JSON schema in the same
request (vLLM guided decoding, or the `llama.cpp` server with a grammar), so
the final step of the agent loop is itself constrained.
**When it is preferable.** If structured answers become a frequent path
(scripts calling CodeSensei), where latency counts.
**Cost.** Same as 3: leaves Ollama; vLLM needs a Linux GPU server, which goes
against "runs on the developer's machine".

### 5. Web search: an API rather than reading result pages

**What we did.** A disposable Chromium reads the HTML results page of a search
engine, without an API key: DuckDuckGo first, then Bing (ADR-0014, ADR-0040).
**What happened.** DuckDuckGo served a bot challenge to one network
(2026-10-14); later Bing answered on the first word of the query only
(2026-10-24: three different Ollama queries returned the same ten generic
results). Each time the tool kept "working" but returned nothing useful.
**Alternative.** A search API: **Brave Search API**, or a self-hosted
**SearXNG** behind the same `BrowserSandbox` / `search_parsing` interface.
**When it is preferable.** As soon as the tool is used outside an educational
project: a key and a quota are cheaper than silent outages and the terms of
use of HTML scraping.
**Cost.** An API key (a secret to store), a quota and a subscription for Brave;
a service to deploy and maintain for SearXNG, which itself queries engines
that can block it.

### 6. Sandboxes: a lighter isolation for plain Python

**What we did.** Every `run_code` call and every web search starts a fresh
Docker container (ADR-0012).
**What happened.** It is safe and well tested (13 out of 13 checks in the
trials of 14 and 24 October), but it needs a Docker daemon on the user's machine, and a 1.1 GB
browser image that took 11 min 52 s to build (2026-10-14) and must be rebuilt
when its policy changes (ADR-0040). The start-up time of a container per call
was not measured.
**Alternatives.** For plain Python: **bubblewrap** or **nsjail** (Linux
namespaces, no daemon, no image), or **Pyodide** (Python compiled to
WebAssembly) when the code needs no native library.
**When it is preferable.** When installation friction matters (a laptop
without Docker, a school machine room), or when `run_code` is called many
times per turn.
**Cost.** bubblewrap/nsjail are Linux-only; Pyodide cannot run every package;
Docker would still be needed for Chromium.

### 7. Project index: build it before the first question

**What we did.** The project is indexed with `bge-m3` at the **first
question** of a session (ADR-0009). Search itself is fast: 1.4 ms for 2,000
passages, 18 ms for 100,000 with numpy.
**What happened.** Indexing is the slow part: 311 s for 106 passages on
8 vCPUs (`bge-m3`; 141 s with `nomic-embed-text`, which ranked worse), and the
user waits on their first question
([R1-rag.md](../performance/R1-rag.md)).
**Alternative.** Index **in the background at start-up** and keep it up to date
with a file watcher (`watchdog`), answering without project passages until the
index is ready.
**When it is preferable.** Beyond a few hundred files, where the first wait
becomes minutes.
**Cost.** A background thread and its error handling; answers of the first
minutes without project context.

### 8. Web interface: generate the client from the server contract

**What we did.** The React interface was first built against a simulated
engine, then plugged into the real FastAPI server (ADR-0020, ADR-0035). The
contract lives in hand-written documents and TypeScript types.
**What happened.** Keeping both sides in line took a dedicated document
reconciling the specification, the user stories and the interface
(`architecture/web/web-api-alignement.md`), which found errors the
specification did not show; two features were still simulated in the
interface at the time (agent hand-offs, MCP tools). Since then hand-offs are
real (ADR-0047, checked with the real model on 2026-11-01); the MCP badge has
never been tried with a real MCP server in the web interface.
**Alternative.** Make the server the single source of truth: FastAPI already
publishes an OpenAPI schema; **openapi-typescript** generates the client types
from it, and the build fails when they no longer match.
**When it is preferable.** As soon as the interface and the server are written
by different people — here from week 2.
**Cost.** A generation step in the front-end build; the streaming events
(SSE) are not fully described by OpenAPI and still need a hand-written type.

### 9. Multi-agent review: an objective check before an LLM reviewer

**What we did.** The team chain explorer → developer → reviewer, where the
reviewer is another model call (ADR-0038).
**What happened.** Given only the developer's report, the reviewer validated
wrong work 6 times out of 6; it became useful (6/6 wrong work caught) only
once it received the exact content written. The chain takes 38 to 65 s
instead of 13 to 23 s for a single agent.
**Alternative.** Before (or instead of) an LLM reviewer, run the **project's
tests in the sandbox** on the modified code, and send the developer the
failing output. A test result cannot be talked into "VALIDÉ".
**When it is preferable.** Whenever the project has tests, which is the usual
case for the code CodeSensei edits.
**Cost.** The project's dependencies must be installable in the sandbox
(network, time); no help on projects without tests.

### 10. MCP: our own client, until remote servers are needed

**What we did.** A hand-written stdio MCP client (ADR-0041): no dependency,
about 200 lines, tested against a fake server.
**Limit.** Stdio transport only, tools only (no resources or prompts); not yet
tried with a published server.
**Alternative.** The official **MCP Python SDK**.
**When it is preferable.** As soon as a remote MCP server (HTTP) or MCP
resources are needed.
**Cost.** Asynchronous code in a synchronous code base, and about ten more
dependencies.

### 11. Generation settings, answer filter and scope: decided at the end, not at the start

**What we did.** Three decisions came last, on 2026-11-01 and 2026-11-02:
generation settings and the loop limit moved to `config.json` (ADR-0057);
the model's answer, and not only the tools, goes through the EV2 filter, and
`/context` shows what is sent (ADR-0058); five features were dropped or
switched off by default (ADR-0056).
**What happened.** Until then the model ran with Ollama's defaults, nobody
had measured tokens/s on our machines, and a secret repeated by the model
could reach the screen. The 28 features of ADR-0008 had been built without
the revision threshold that ADR-0008 itself set ever being applied.
**Alternative.** Treat these three as **day-one choices**: a `generation`
section and a speed benchmark with the first Ollama call (the script
[`bench_generation.py`](../../scripts/bench_generation.py) is 212 lines); one output filter next to the input filter of ADR-0027; a scope
review on the revision date that ADR-0008 had set (2026-10-18).
**When it is preferable.** Always for the first two: they cost little early
and touch every call later. The scope review, as soon as a persona exists:
X3 public links and the 3D layer would not have been built for Camille.
**Cost.** Not timed. What it took late: changes to the CLI, the web server,
the scheduler and their tests for the settings; a line-by-line stream filter
(a secret can arrive split across chunks); three visual ADRs (0021, 0025,
0026), whose 3D scene and animated code universe were removed. Earlier, the same work would have been smaller
and nothing would have been removed.

## Team, hardware and schedule

The sections above look at the code. This one looks at how the work was
organised, what our machines allowed, and planned dates against real ones.
Sources: the team's ClickUp planning (due dates), the GitHub pull requests
and the git history, counted on 2026-11-03.

### 12. Team: pull requests merged without a review

**What we did.** Four people, one lot each (A brain, B hands, C memory,
D interface), one branch and one pull request per change, as `CONTRIBUTING.md`
asks. Nothing on GitHub enforced the review: `main` had no rule requiring
an approval before merging.
**What happened.** **53 of the 78 merged pull requests had no review**:

| Author | Merged PRs | Without review | Commits (no merges) |
| --- | --- | --- | --- |
| Ridwane (Lot C) | 52 | 47 | 183 |
| Meric (Lot B) | 16 | 5 | 85 |
| Fresnel (Lot A) | 9 | 0 | 137 |
| Christopher (Lot D) | 1 | 1 | 41 |

The workload was uneven too: one person opened two thirds of the pull
requests. Without a second reader, a change was only checked by its author's
own tests.
**Alternative.** A branch protection rule on `main`: one approval required,
the CI (`.github/workflows/ci.yml`) required green, and a `CODEOWNERS` file
naming each lot's owner, so that a change to another lot's code asks that
lot's owner.
**When it is preferable.** From the first pull request, for any team of more
than one.
**Cost.** Waiting for a reviewer: a pull request can stay open for hours,
which pushes towards smaller pull requests and a fixed review slot each day.

### 13. Hardware: no machine of the team runs the validated model

**What we had.** The team's reference machine has 4 GB of VRAM and 16 GB of
RAM ([ADR-0004](../decisions/0004-modele-et-infrastructure.md)). The
validated model, `qwen3-coder:30b`, needs a 24 GB GPU (21.7 GB of VRAM
measured). `qwen3:8b` on a laptop without GPU generates 4.5–4.8 tokens/s
([generation-parameters.md](../performance/generation-parameters.md)): too
slow for the agent loop. The sandbox and the web search need Docker
(a 1.1 GB image).
**What happened.** Every trial with the real model, every recording and the
demo depend on a rented RunPod pod; a new pod means installing Ollama and
downloading about 20 GB of models again. Day-to-day development used tests
with a scripted model, so several behaviours were first seen with the real
model days after they were merged (for example the project's tests as the
team's verdict: merged on 2026-11-02, tried in both cases on 2026-11-03).
**Alternative.** One shared workstation with a 24 GB GPU (RTX 3090 / 4090
class) for the team, or a pod kept with a persistent volume from the first
week, and a short trial with the real model in each pull request that
changes the agent's behaviour.
**When it is preferable.** As soon as the validated model does not fit on
the team's machines, which ADR-0004 measured in the first week.
**Cost.** A second-hand RTX 3090 workstation, or 0.22–0.44 $/h of rented GPU
(estimated, [couts.md](../business/couts.md)), plus the time of each trial.

### 14. Schedule: planned dates against real ones

**Planned** (ClickUp milestones, due dates):

| Milestone | Planned |
| --- | --- |
| J0 Bootstrap, base loop working | 2026-09-21 |
| Checkpoint 1, scope validated | 2026-09-27 |
| S2 Brain, hands and memory integrated (ReAct, MCP, sandbox, RAG) | 2026-10-04 |
| S3 Guardrails and human in the loop | 2026-10-11 |
| S4 Web interface complete, user stories written (A4, M4, EV4, T5, EV3, T3, M3, X5, T4, A7, A5, X3) | 2026-10-18 |
| S5 Deliverables assembled, demo rehearsed (X4, X2, A6, R2, EV1, M2, A2) | 2026-10-25 |
| Keynote script and rehearsals | 2026-10-30 |
| Final delivery and keynote | 2026-11-01 |

**Pushed back** (real date: the ADR that delivered it, first committed):

| Feature | Planned | Delivered | Late by |
| --- | --- | --- | --- |
| A5 Persona | 2026-10-18 | 2026-10-26 (ADR-0042) | 8 days |
| A7 Prompt optimisation | 2026-10-18 | 2026-10-28 (ADR-0044) | 10 days |
| X3 Share links (real) | 2026-10-18 | 2026-10-29 (ADR-0048) | 11 days |
| M2 Token budget | 2026-10-25 | 2026-10-28 (ADR-0045) | 3 days |
| X4 Questions and forms | 2026-10-25 | 2026-10-29 (ADR-0046) | 4 days |
| Scope review (ADR-0008's revision date) | 2026-10-18 | 2026-11-01 (ADR-0056) | 14 days |

The real web server (ADR-0035, 2026-10-18) came on its planned date. The
user stories, planned for 2026-10-18, were still being rewritten on
2026-11-02 (75 commits on `docs/user-stories/`). Work went on after the final
delivery date: generation settings, output filter, trials of 2026-11-02 and
2026-11-03. The ClickUp statuses were not kept up to date (X4 is still
"to do" although delivered), so the real dates above come from git, not
from ClickUp.

**The most time-consuming tasks**, measured in commits and changed files,
not in hours (no time was logged):

| Task | Commits | File changes | Period |
| --- | --- | --- | --- |
| Web interface (`frontend/`) | 60 | 415 | 2026-10-13 → 2026-11-02 |
| User stories (`docs/user-stories/`) | 75 | 261 | 2026-10-11 → 2026-11-02 |
| ADRs (`docs/decisions/`) | 114 | 261 | 2026-09-22 → 2026-11-02 |
| Demo recordings (`docs/demo/`) | 17 | 169 | 2026-10-13 → 2026-11-02 |

Work came in two peaks: 173 commits in the week of 12 October and 182 in the
week of 26 October, against 2 in the week of 28 September.
**Alternative.** Keep ClickUp as the one place for status (each pull
request closes its task), review the plan each Monday against what is
merged, and cut scope on the planned revision date instead of two weeks
later. The decorative web layer (3D scene, animated code universe), built
then removed (section 11), would not have been started.
**When it is preferable.** From the first milestone.
**Cost.** About fifteen minutes a week for the plan review, and tasks that
cannot be closed without their pull request.

## Summary

| Component | Alternative | Main gain | Becomes preferable | Cost |
| --- | --- | --- | --- | --- |
| Guardrails | Filter in the Ollama client | Risk: leaks impossible by construction | More than one prompt builder | One filter pass per call, over-masking |
| Orchestration | Deterministic router | Reliability on clear cases | Demos, paying users | Rigid on phrasing |
| Tool calling | Tool routing; constrained decoding | Reliability (1/6 → 8/8 measured with one tool) | More than a handful of tools | Hidden tools; leave Ollama |
| Structured output | Tools + schema in one call | Time (one call instead of two) | Frequent scripted use | Leave Ollama |
| Web search | Brave Search API, SearXNG | Risk: no silent degradation | Any non-educational use | Key, quota, service |
| Sandboxes | bubblewrap / nsjail / Pyodide | Installation, start-up | No Docker, many calls per turn | Linux-only or limited packages |
| Project index | Background indexing + watcher | Time: no wait on first question | Hundreds of files | A background thread |
| Web interface | Client generated from OpenAPI | Time: no contract drift | Separate front/back authors | A build step |
| Code review | Project tests in the sandbox | Reliability: objective verdict | Projects with tests | Installable dependencies |
| MCP | Official SDK | Coverage of the protocol | Remote servers | Async code, dependencies |
| Settings, output filter, scope | Decide them with the first model call and on ADR-0008's revision date | Risk and time: nothing reworked or removed late | From the start | A benchmark script and a filter written early |
| Team | Branch protection: one approval, CI green, `CODEOWNERS` per lot | Risk: no change checked only by its author (53 of 78 PRs had no review) | From the first PR | Waiting for reviewers |
| Hardware | One shared 24 GB GPU workstation, or a persistent pod from week one | Time: the real model tried in each PR, not days later | When the model does not fit the team's machines | Hardware or rented GPU hours |
| Schedule | One status source, weekly plan review, scope cut on the planned date | Time: no feature built then removed; fewer late features (up to 14 days late) | From the first milestone | About 15 min a week |

There is no load-test section on purpose: CodeSensei runs locally for one
developer, so what matters is latency and GPU memory on a developer machine,
not concurrent users.

## What we would keep without hesitation

- **No LLM framework** (ADR-0001): every behaviour is readable and testable;
  that is what made each defect of the full trial fixable within hours.
- **A single tool gateway** (ADR-0006): sub-agents (A2) and MCP tools (T1)
  inherited confirmations, permissions and guardrails without duplicated code.
- **Deciding on measurements**: A2, T5 and web search changed approach because
  of a number (a reviewer validating 6 wrong results out of 6, 0 right JSON
  answers out of 15, the same results for three different queries).
- **The project file kept up to date as we went**: ADRs, user stories,
  measurements with their scripts.

## Next actions

1. Move the guardrail filter into the Ollama client (section 1). *Partly done on
   2026-11-01*: the model's answer and reasoning are filtered in the agent loop
   (ADR-0058) and every tool result is fenced as untrusted data (former gap
   EV4-OUT-14); the filter is still not in the client itself.
2. Add a deterministic router for delegation and team hand-off (section 2).
3. ~~Run the project's tests in the team chain (section 9)~~: done on
   2026-11-02 (ADR-0056, item 3), on the machine rather than in the sandbox
   (its image has neither the project nor its dependencies); seen with the
   real model on 2026-11-03, passing and failing
   ([trial](../performance/essais/essai-2026-11-03.md)).
4. ~~Deliver M2, A5 and A7, or remove them from the scope~~: delivered
   (ADR-0045, ADR-0042/0043, ADR-0044); the scope decision is ADR-0056.
5. ~~Plug agent hand-offs and MCP tools into the web interface~~: done
   (ADR-0047).
6. ~~Measure `qwen3:8b` on a team laptop with `scripts/bench_generation.py`~~:
   done on 2026-11-02, 4.5–4.8 tok/s on the CPU
   ([generation-parameters.md](../performance/generation-parameters.md)).
7. Protect `main`: one approval and the CI required before merging, with a
   `CODEOWNERS` file per lot (section 12).
