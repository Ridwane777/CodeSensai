# Project dossier - document map

Entry point for following the work **without reading the code**: how to use
it, how it is built, what we decided, what it implies, what we take away from
it. Keep this map up to date with
every document added.

As of 2026-11-16.

## Use

| Document | Content |
| --- | --- |
| [features.md](features.md) | Catalogue of every delivered feature: what it does, how to use it, its ADR, user stories and measurements |
| [known-limits.md](known-limits.md) | What does not work yet, or only with conditions |
| [guide/run-and-use.md](guide/run-and-use.md) | Install, launch the CLI, choose the model and the Ollama server, plug in an MCP server (the web server: [web-api.md](architecture/web/web-api.md)) |
| [design/persona-and-scenario.md](design/persona-and-scenario.md) | The user (Camille, developer; Marc, lead), her day step by step (S0–S9), and what "local" means vs the rented GPU |
| [demo/](demo/README.md) | Demo script (including the [scenario-driven script](demo/README.md#scenario-driven-script)), recordings, fallback plan |

## Understand the architecture

| Document | Content |
| --- | --- |
| [architecture/architecture.md](architecture/architecture.md) | Overview, components and responsibilities, contracts between the lots, known limits |
| [architecture/tool-contract.md](architecture/tool-contract.md) | Contract of the tools and of the gateway (in English) |
| [architecture/sandbox.md](architecture/sandbox.md), [sandbox-design.md](architecture/sandbox-design.md), [sandbox-walkthrough.md](architecture/sandbox-walkthrough.md) | Disposable containers: how they work, why Docker, history (in English) |
| [architecture/scheduling.md](architecture/scheduling.md) | Scheduled tasks (X5): commands, cron, unattended policy |
| [architecture/web/](architecture/web/web-api.md) | Web server and interface: [API](architecture/web/web-api.md), [event contract](architecture/web/api-contract.md), [alignment](architecture/web/web-api-alignment.md), [what is real or simulated](architecture/web/simulated-vs-real.md) |

## Decisions and trade-offs

| Document | Content |
| --- | --- |
| [decisions/](decisions/README.md) | 58 ADRs (Nygard / MADR format) and their index, with status; template: [TEMPLATE.md](decisions/TEMPLATE.md) |
| [research/](research/model-choices.md) | Exploration notes that fed the ADRs: [model choice](research/model-choices.md), [infrastructure options](research/infra-options.md) (in English) |
| [design/web_facade_spike.py](design/web_facade_spike.py) | Web facade prototype that preceded the real server (ADR-0022, ADR-0023), tested by `tests/web/` |
| [user-stories/](user-stories/README.md) | 35 files, at least two stories per feature, with their verified status; [index](user-stories/README.md) feature → file → persona |
| [design/traceability.md](design/traceability.md) | Traceability matrix: feature → stories → ADR → code → tests → scenario step |

## Impacts

| Type | Document | Content |
| --- | --- | --- |
| Legal | [legal/](legal/README.md) | Risk analysis, privacy, terms of use, legal notices, licenses, local data |
| Security | [security/EV4-adversarial-tests.md](security/EV4-adversarial-tests.md) | Adversarial tests: 85 cases, 20 known gaps tracked ([generated results](performance/data/EV4-adversarial-results.md)) |
| Performance | [performance/](performance/) | Measurements per feature, each with its script in `scripts/`: [M1](performance/M1-sessions.md), [R1](performance/R1-rag.md), [R2](performance/R2-rag.md), [M3](performance/M3-facts.md), [M4](performance/M4-state.md), [A2](performance/A2-orchestration.md), [A4](performance/A4-prompts.md), [A6](performance/A6-cache.md), [T3](performance/web-search.md), [T5](performance/T5-structured.md), [EV1](performance/EV1-evaluation.md), [#64](performance/64-documents.md), [real web](performance/real-web.md), [generation parameters and tokens/s on the pod GPU](performance/generation-parameters.md). No load test: single-user local tool ([retrospective](retrospective/README.md)) |
| Full trials | [performance/trials/](performance/trials/trial-2026-11-06.md) | **Reference: [2026-11-06](performance/trials/trial-2026-11-06.md)**, every feature on both set-ups: `qwen3:8b` on the team laptop (CPU, 26 of 28 scenarios, 7–11 min a turn) and `qwen3-coder:30b` on a 24 GB GPU (all 28 after reruns and the day's fixes, A3 in the web 2 of 4; 4–20 s a turn), script `scripts/trial_features.py`. Earlier trials: [2026-10-13](performance/trials/trial-2026-10-13.md), [2026-10-14](performance/trials/trial-2026-10-14.md), [2026-10-24](performance/trials/trial-2026-10-24.md), [2026-11-01](performance/trials/trial-2026-11-01.md), [2026-11-01 afternoon](performance/trials/trial-2026-11-01-evening.md), [2026-11-02 (whole scenario, one video)](performance/trials/trial-2026-11-02.md), [2026-11-03 (ADR-0056 limits and EV2 answer filter)](performance/trials/trial-2026-11-03.md), [2026-11-06 (every feature with qwen3:8b on a CPU laptop)](performance/trials/trial-2026-11-06.md) |
| Costs | [business/costs.md](business/costs.md) | Measured and estimated kept apart, each with its method; the real RunPod invoice is still to be reported |
| Known bugs | [backlog.md](backlog.md) | Known bugs and adversarial gaps as of 2026-11-01, prioritised (P1 to P3), each with where it was found and a possible fix |
| Dependencies | [dependencies.md](dependencies.md) | APIs, libraries, models, services, secrets, licenses, and what happens if one disappears; versions in `requirements*.txt` |

## Hindsight and business side

| Document | Content |
| --- | --- |
| [retrospective/](retrospective/README.md) | Global look back: what we would do differently, what would have cut costs, time and risks, what we keep, next actions |
| [decisions/0056](decisions/0056-scope-review-features-to-drop-or-limit.md) | Features dropped or limited (accepted 2026-11-02) (3D layer removed, share links and cache off by default), completing ADR-0008 |
| [decisions/0057](decisions/0057-generation-parameters-and-loop-limit.md) / [0058](decisions/0058-filtered-answers-and-context-command.md) | Generation parameters and loop limit from the configuration; the model's answer filtered while it streams, `/context` (both accepted) |
| [business/business-plan.md](business/business-plan.md) | Problem, solution, competition, business model, SWOT, roadmap, team |
