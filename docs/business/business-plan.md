# Business plan - CodeSensai

Written on 2026-10-25; translated from French and updated on 2026-11-01 (test
and ADR counts, delivered features, local vs rented GPU). Educational project: this plan describes what CodeSensai would be as a
product, based on what exists and was measured. Cost figures are in
[costs.md](costs.md), with their method. No market size is given, for lack of
a verified source.

## 1. The problem

The most widespread AI coding assistants send the developer's code to a model
provider, on a subscription. Three groups struggle with that:
- companies whose code must not leave (regulated sectors, code under a
  confidentiality agreement, defence, health);
- developers who work offline or on a filtered network;
- schools and small teams that do not want a per-seat subscription.

## 2. The solution

CodeSensai is a **developer agent meant to run locally** with an open model
served by Ollama: it reads the project, runs code in a sandbox, edits files
after confirmation, remembers the project from one session to the next, and
can hand a change to a team of agents that review each other. What is
delivered and checked with the real model
([trial of 2026-10-24](../performance/trials/trial-2026-10-24.md),
[trial of 2026-11-01](../performance/trials/trial-2026-11-01.md)):

- agent loop with native tools, confirmation before any risky action;
- code execution and web search in disposable containers;
- memory: sessions, saved facts, project state document, search in the
  project (hybrid, with re-ranking), answer cache, token budget with a
  sliding summary;
- guardrails: secrets and personal data masked before the model, and in the
  model's own answer;
- specialised agents that pass the work on, reviewer included; configurable
  personas; automatic few-shot examples;
- external MCP tools, JSON output following a schema, scheduled tasks,
  evaluation by a judge, web interface.

**What sets it apart**: no API key is required, and every risky action goes
through a confirmation and tested guardrails (85 adversarial cases: 66
stopped - 45 blocked, 12 masked, 9 flagged - and 19 known gaps tracked, EV4).
The code stays on the machine **only if the model runs on that machine**: our
demos and measurements used a rented GPU (RunPod), because none of our laptops
can run the 30B model at a usable speed. The trade-offs are on the
[persona page](../design/persona-and-scenario.md#local-vs-rented-gpu).

## 3. Market and competition

| Offer | Model | Where the model runs | What CodeSensai does differently |
| --- | --- | --- | --- |
| GitHub Copilot, Cursor | Per-seat subscription | At the provider | Local, no subscription |
| Command-line agents of model providers | Subscription or pay per use | At the provider | Local; open model of your choice |
| Aider, Continue, Cline (open source) | Free; model of your choice, local possible | Local or remote | Project memory, team of agents, built-in and tested guardrails and confirmations |

Online competitors have stronger models than what runs on a 24 GB GPU:
CodeSensai does not win on raw quality, but on confidentiality, fixed cost and
control.

## 4. Business model (assumptions)

The core stays free (MIT / Apache-2.0 licences for every dependency,
[licenses.md](../legal/licenses.md)). Revenue ideas, to be validated with
customers:

1. **Enterprise licence**: deployment on the company's machines, guardrail
   rules and internal MCP servers preconfigured, support.
2. **Training offer**: installation in training rooms, no per-seat
   subscription.
3. **Consulting**: choice of model and hardware, integration with internal
   tools through MCP.

Running cost for the user: none in services (free licences, no paid API); the
cost is the hardware (24 GB GPU for the 30B model) or renting a GPU by the
hour (≈ $0.22 to $0.44/h, [costs.md](costs.md)).

## 5. SWOT

| Strengths | Weaknesses |
| --- | --- |
| No API key; code stays on the machine when the model runs locally | Quality limited by a 30B model on 24 GB |
| Tested guardrails and confirmations (1,652 tests, adversarial corpus) | Demanding hardware (24 GB GPU) for the measured quality; our own demo relied on a rented GPU |
| Readable architecture, no framework (ADR-0001) | Some behaviours depend on the model (see the [user-stories audit](../user-stories/README.md)); a few web features still partial |
| Decisions documented and measured (58 ADRs) | Web search depends on HTML pages (ADR-0040) |

| Opportunities | Threats |
| --- | --- |
| Open models improve fast: the same architecture benefits without change | Online providers add "on-premises" offers |
| Demand for confidentiality (code under agreement, regulated sectors) | Existing open-source tools (Aider, Continue, Cline) already hold the ground |
| MCP becomes a standard: plug in a company's internal tools | Terms of use of search engines read without an API |

## 6. Roadmap

| Stage | Content | Condition to move on |
| --- | --- | --- |
| Short term | Close the gaps found by the stories audit (untrusted tool results fenced, reasoning text filtered, web sources in the interface); scope decision of ADR-0056 | Full trial of every feature with no defect |
| Medium term | Scripted end-to-end trial every week; web search API; trial with published MCP servers | First pilot users (a school, a team) |
| Long term | Enterprise offer (guardrail rules, internal MCP, support) | Pilot feedback and measured support cost |

## 7. Team

| Lot | Person | Responsibility |
| --- | --- | --- |
| A - Brain | Fresnel | agent loop, prompts, multi-agent, structured output |
| B - Hands | Meric | tools, sandbox, web search, gateway, evaluation |
| C - Memory | Ridwane | sessions, RAG, facts, state document, cache |
| D - Interface | Christopher (GitHub: Christopher142769) | web interface, MCP |

## 8. Costs

Detail and method: [costs.md](costs.md). In short: licences and services at
€0 (measured); development GPU in the order of a few tens of dollars
(estimated, to be replaced by the invoice); development time estimated at 190
to 380 person-hours, the largest cost item.
