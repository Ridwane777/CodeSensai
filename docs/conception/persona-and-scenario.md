# Persona and usage scenario

> **Update on 2026-11-01:** a usage scenario already existed ("a developer in
> her code base"), but it did not fit the project well enough: no precise
> user, no concrete situation, and a latency that was not realistic on our
> hardware. It was updated into this page: **one** user, **one** day of work,
> and what "local" really means for CodeSensei
> ([Local vs rented GPU](#local-vs-rented-gpu)).

Every user story names the persona it serves (index:
[user-stories/README.md](../user-stories/README.md)); each feature is linked to
its step of the scenario in [traceability.md](traceability.md); the demo
follows the same steps ([demo script](../demo/README.md#scenario-driven-script)).

The people below are fictional.

## Primary persona — Camille Roux, developer who inherits a code base

| | |
| --- | --- |
| Role | Back-end Python developer, 3 years of experience |
| Company | A 15-person software firm (an SME) that builds invoicing and reporting tools for accounting offices |
| Situation | Has just taken over a small Python code base (a few dozen files, tests with `pytest`) written by a colleague who left. Little documentation, no one left to ask |
| Constraint | The client contracts forbid sending the clients' code or data to a third-party cloud API: no hosted assistant (Copilot, ChatGPT, Claude…) on this code |
| Machine | A company laptop with no usable GPU, comparable to the team's reference machine (4 GB of VRAM, 16 GB of RAM, [infra-options.md](../recherche/infra-options.md)). The firm may buy one workstation with a 24 GB GPU, or rent one by the hour |
| Tools | Terminal, VS Code, git; she uses CodeSensei in the terminal (`sensai`) and in the browser (`sensai-web`) |

**Goals**
- Understand the code base quickly enough to fix bugs in her first week.
- Change code without breaking it: see every change before it is written,
  run it somewhere safe.
- Keep track of what was decided, so that the next person does not start
  from zero like she did.

**Frustrations**
- Reading every file by hand to find where something is done.
- Cloud assistants are forbidden on this code; generic answers "from memory"
  do not know her project.
- An assistant that writes files or runs commands without asking.
- Losing the thread when she closes the terminal at the end of the day.

## Secondary persona — Marc Dubois, tech lead who sets the tool up

| | |
| --- | --- |
| Role | Tech lead of the same firm, responsible for the tools the developers use and for what leaves the company network |
| Goal | Give the team an assistant that respects the confidentiality rule, with guardrails he can configure and check, without being a machine-learning expert |
| What he touches | `config.json` (personas, file permissions, blocked topics, MCP servers, few-shot examples), the prompt versions, the evaluation and the adversarial tests, the scheduled tasks; in the web interface: the Prompts, Quality, Planning and Journal pages |
| Frustration | Being asked "is it safe?" and "did the new prompt make it worse?" without a way to answer with facts |

Marc is the persona of the "team tools" (A4 prompt versions, EV1 evaluation,
EV4 adversarial tests, part of A5, EV2, T1, T4 and X5). Camille is the persona
of everything else.

## The day Camille fixes the invoice report

The project used in the trials and the recordings is a throwaway folder whose
`stats.py` has a `moyenne` function that crashes on an empty list
([trial of 2026-11-01](../performance/essais/essai-2026-11-01.md)); here it
stands for Camille's invoice report, whose monthly average crashes for a client
with no invoice. Steps are numbered **S0 to S9**; [traceability.md](traceability.md)
and the demo script use the same numbers.

**S0 — Before Camille arrives (Marc).** Marc installs CodeSensei on the
machine that will run the model, writes `config.json`: a "reviewer" persona
next to the default one, `files.write = ["src"]`, a blocked topic (salaries),
the company's MCP server, a few-shot file with two good answers. He checks the
prompt version in use (`v3`) on the Prompts page.
*Features: B1, A5, T4, EV2, T1, A7, A4.*

**S1 — Monday, 9:00: she resumes.** Camille opens `sensai-web`, reopens
Friday's conversation from the sidebar and asks to pick up where she left off.
The agent knows her preferences (pytest, answers in French) and the facts it
saved about the project.
*Features: M1, X1, M3.*

**S2 — 9:05: she asks how to run the tests.** The agent searches the project,
answers with `pytest -q` and cites the file it comes from; the answer says it
was inspired by one of Marc's few-shot examples.
*Features: R1, R2, A7.*

**S3 — 9:15: the bug.** A client reports that the monthly report crashes.
Camille asks the agent to find out why. The agent reads `stats.py`, runs the
function in the disposable sandbox (no network, 256 MB, 10 s), sees the
`ZeroDivisionError`, and explains the cause.
*Features: A1, T4, T2, T1 (native tool calling).*

**S4 — 9:25: the fix, approved.** The agent proposes to rewrite the function
with `write_file`. Camille sees the coloured diff; she first answers "no, raise
a ValueError instead", the agent changes its fix; she allows the second
version. A file read that the agent tries outside the project is refused.
*Features: A3, T4.*

**S5 — 10:00: a missing piece of information.** She asks the agent to add a
test file; the agent asks her, in a form inside the chat, the file name and
the style she wants, then reuses her answers.
*Features: X4.*

**S6 — 10:30: a wider change.** The report also needs a median. Camille asks
for it; the agent hands the task to its team (explorer → developer →
reviewer), and the relays appear in the conversation.
*Features: A2, X1.*

**S7 — 11:00: outside knowledge, and secrets.** She asks which `pytest`
version is current: the agent searches the web from an isolated browser and
cites python.org-style sources instead of a number from memory. She then asks
it to look at `deploiement.txt`, which holds an AWS key: the key is masked
before the model sees it. A company tool reached through MCP answers a lookup;
a key it returns is masked too.
*Features: T3, EV2, T1.*

**S8 — Afternoon: memory and a long session.** She asks the agent to note the
decision ("empty list → ValueError") in the project's state document
`SENSAI.md`, and it saves the fact "monthly report: requires at least one
invoice". The session grows long: the token bar fills, old messages are
summarised to stay within budget. When she asks the tests question again in a
new conversation, the answer comes from the semantic cache in under a second.
She stops a long answer that goes the wrong way, edits her message and sends a
variant; she asks for a JSON list of the functions of `stats.py` for a ticket
script (`/structured`).
*Features: M4, M3, M2, A6, X2, T5.*

**S9 — 17:30: hand-over.** She asks the agent to schedule a summary of the
day's changes every morning (`schedule_task`), exports the conversation and
creates a read-only share link for Marc, secrets masked. Marc opens the Journal
page to see each tool call and its duration, evaluates the last answer on the
Quality page (relevance, coherence, faithfulness to the sources), replays the
85 adversarial attacks from the same page, tries the previous prompt version in
a conversation from the Prompts page, and switches to the "reviewer" persona to
check that its disabled tools are refused.
*Features: X5, X3, EV3, EV1, EV4, A4, A5.*

## Local vs rented GPU

We present CodeSensei as "local", yet no machine of the team runs the model
we validate it with.

**What we measured.**
- The team's reference machine has **4 GB of VRAM, 16 GB of RAM** and 19 GB of
  free disk ([ADR-0004](../decisions/0004-modele-et-infrastructure.md),
  [infra-options.md](../recherche/infra-options.md)).
- The validation model, `qwen3-coder:30b`, is an **18.6 GB** download and took
  **21.7 GB of VRAM** with a 32,768-token context on the pod (`ollama ps`,
  [R1-rag.md](../performance/R1-rag.md), GPU trial section). It needs a 24 GB
  GPU.
- In development we use `qwen3:8b` (~5 GB in Q4, ADR-0004). On CPU, in the
  [R1 CLI trial](../performance/R1-rag.md): with the 5 default passages the model
  took more than 60 s before its first word and the client timed out; with 2
  passages one answer took **about 6 min 45 s**. That is not usable for an
  agent loop that calls several tools per turn.
- Every trial with the validation model and every recording ran on a **rented
  RunPod pod with a 24 GB GPU**, reached over HTTP (the pod address is never in
  the repository). Latencies measured that way, from the
  [trial of 2026-11-01](../performance/essais/essai-2026-11-01.md): first
  question 91 s (indexing + model loading), a file fix with its diff 13.1 s, a
  form round trip 7.8 s, a delegation 14.0 s, a team task 52.7 s, a repeated
  question 16.2 s from the model and 0.6 s from the cache. A cold pod made the
  first answer take more than 2 minutes
  ([afternoon trial](../performance/essais/essai-2026-11-01-soir.md)).
- Generation speed of `qwen3-coder:30b` on the pod's GPU: about **119
  tokens/s** ([generation-parameters.md](../performance/generation-parameters.md)).
  The same measure for `qwen3:8b` on a team laptop without GPU (i7-1355U,
  2026-11-02): about **4.5–4.8 tokens/s**, about 7 s for a short answer
  ([generation-parameters.md](../performance/generation-parameters.md)).

**What "local" means here.** CodeSensei has no server of ours and calls no
third-party AI API. The code, the index, the sessions, the facts and the
journal stay in files on the machine where `sensai` runs
([legal/](../legal/README.md)). Ollama runs on a machine **the user controls**:
her own workstation, or a GPU she rents by the hour and can switch off. A
rented pod is not the same as a cloud API (no provider reads the prompts to
answer them, no usage terms on the content), but the code does travel to a
machine in someone else's data centre. For Camille's confidentiality clause,
**only the first option is fully clean**; the rented pod is acceptable only if
the client contract allows hosting with a chosen provider.

**What machine makes it really local.**

| Setup | What it gives | Source |
| --- | --- | --- |
| Workstation with a 24 GB GPU (RTX 3090 / 4090 class) | The validated model, `qwen3-coder:30b`, in the same conditions as our trials | ADR-0004; 21.7 GB measured in [R1-rag.md](../performance/R1-rag.md) |
| Smaller GPU (8–16 GB) with `qwen3:8b` | Runs, but every feature was validated on the 30B model: tool calls and instructions may be followed less well. **Not measured**: no comparative trial in the repository ([couts.md](../business/couts.md), section 2.3) | ADR-0004 |
| CPU only with `qwen3:8b` (Camille's laptop today) | Works for a short question (about 7 s, 4.5–4.8 tok/s measured on 2026-11-02), too slow for the agent loop (a turn reads thousands of tokens at about 10 tok/s: minutes) | [generation-parameters.md](../performance/generation-parameters.md), [R1-rag.md](../performance/R1-rag.md) |
| Rented 24 GB GPU (RunPod) | Our demo setup; estimated 0.22–0.44 $/h in Community Cloud | [couts.md](../business/couts.md), estimated, not invoiced |

So, for the scenario to be true as written, Marc's firm buys **one workstation
with a 24 GB GPU** that runs Ollama for the team (the CLI can point to it with
`--host`), or accepts the smaller model and its unmeasured loss of quality.
The demo, by necessity, uses the rented pod; we say so on stage.

**Our position.** In development, we chose `qwen3:8b` because we could not
install `qwen3-coder:30b` on our machines. Users install `qwen3-coder:30b`
locally, on their own machine.
