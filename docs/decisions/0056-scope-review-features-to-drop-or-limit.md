# ADR-0056 — Features we drop or limit

- **Status**: Accepted (2026-11-02, decided by Ridwane, Lot C): all five items applied
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C)
- **Lot concerned**: All. Completes [ADR-0008](0008-scope-all-features.md)
  (which stays accepted as the record of the decision taken on 2026-10-11)

## Context

ADR-0008 chose to implement the 28 catalogue features, against the advice of
the catalogue itself (page 1: a group with fewer, well-integrated features is
better evaluated). It set a revision threshold that was never applied: if the
A, B and C bricks were not merged by 2026-10-18, drop first X5 Scheduling,
X3 Export and A7 Prompt optimisation. Until this decision, **no feature had
been dropped on purpose**.

Since then we have a precise persona and scenario
([persona-and-scenario.md](../design/persona-and-scenario.md)): Camille,
who takes over a Python code base she may not send to a cloud API, and Marc,
the lead who sets the tool up. We also have measurements, trials and a list of
known defects ([backlog.md](../backlog.md),
[retrospective](../retrospective/README.md)). This ADR asks, feature by
feature, whether it serves that scenario and whether it was worth its cost.

Evidence used:

| Feature | What it gives Camille or Marc | What it cost or showed | Source |
| --- | --- | --- | --- |
| X1, decorative layer (3D scene, animated "code universe", poster hero) | Nothing in the scenario: Camille opens the chat to work | Three ADRs, a WebGL fallback, a simulated engine kept alongside the real server; a reconciliation document was needed to keep both in line | [ADR-0021](0021-3d-visual-and-animations.md), [0025](0025-poster-style-home-hero.md), [0026](0026-animated-code-universe.md), retrospective section 8 |
| X3, public share links | Showing the session to Marc | A snapshot readable **without the token** for 7 days, revocable only through the API: in tension with Camille's confidentiality clause. Plain export covers the need | [ADR-0048](0048-share-links.md), [demo pitfalls](../demo/README.md#known-pitfalls) |
| A6 Semantic cache | Instant answer to a repeated question | 7 rephrasings out of 39 served (0 of 48 traps): for one developer, few questions repeat; one more store to invalidate | [A6-cache.md](../performance/A6-cache.md), README |
| A2 team chain (explorer → developer → reviewer) | Wider changes | Reviewer validated wrong work 6 times out of 6 until it received the written content; 38–65 s instead of 13–23 s; in the 2026-11-01 trial the developer wrote a new file and the reviewer validated it | retrospective section 9, [trial 2026-11-01](../performance/trials/trial-2026-11-01.md) |
| A5 keyword routing and session personas | A tutoring or support platform, not Camille's day | Persona name not always followed after a switch | [ADR-0043](0043-persona-enhancements.md), backlog #10 |
| A7 automatic few-shot | Answers styled on Marc's examples | A French example once won over an explicit "answer in English" preference | trial 2026-11-01, finding 3 |
| X5 Scheduling | A morning summary | Unattended runs need their own policy; marginal in the scenario | [ADR-0016](0016-task-scheduling.md), ADR-0008 threshold |

The rest (B1, A1, A3, A4, M1–M4, R1, R2, T1–T5, EV1–EV4, X2, X4, the chat of
X1) is used at a step of the scenario and has measurements or trials behind
it: kept as is ([traceability.md](../design/traceability.md)).

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep the 28 as they are | No work; full catalogue coverage | No feature dropped on purpose; keeps features that weaken the confidentiality story (public links) or that fail in demos (team reviewer) |
| Remove the weakest features from the code | Smaller surface, simpler demo, fewer tests to keep green | Code removed late; features of the catalogue lost; risk of breaking what works |
| **Limit or switch off by default, keep the code** | Aligns the product with the scenario; reversible; each change is small and testable | Features still present to maintain; "off by default" can look like hiding |

## Decision

Accepted on 2026-11-02. What was applied in the code is marked after each item.

1. **Drop** the decorative layer of X1 (3D scene, animated code universe) from
   the product; the home page becomes the chat. The simulated engine stays
   only as the demo fallback. **Applied**: the 3D scene, the WebGL detection, the
   animated code universe and the `three` dependencies are removed from `frontend/`.
2. **Limit X3** to local export (Markdown, JSON, print to PDF); public share
   links are **off by default**, behind a config switch Marc must turn on. **Applied**: the
   repository's `config.json` does not enable them, so `POST /api/sessions/{id}/share`
   answers 403 `SHARE_DISABLED`; Marc turns them on by adding `"share_links": true`
   to `config.json` (`tests/web/test_shares.py`).
3. **Limit A2** to `delegate_task` (one sub-agent); replace the LLM reviewer of
   `team_task` by running the project's tests in the sandbox before any
   "validated" verdict (retrospective section 9). **Applied** (2026-11-02): when
   the project has tests, `team_task` runs `pytest -q -x` in the project and its
   result is the verdict (`tools/project_tests.py`); without tests the reviewer
   keeps its role. The tests run on the machine, not in the sandbox (its image has
   neither the project nor its dependencies): `team_task` is an "execute" action
   the user approves first. `delegate_task` is kept.
4. **Limit A5** to configured personas with tool restrictions (Marc's
   "reviewer"); drop keyword routing and session-only personas (ADR-0043). **Applied**
   (2026-11-02): `auto_route` and `/persona add` are removed; a `keywords` field
   in `config.json` stops the program with a message (A5 stories 3 and 5 withdrawn).
5. **Keep A6, A7 and X5, off by default**: cache and few-shot opt-in in
   `config.json`, scheduling only through `sensai-schedule` and
   `schedule_task`, documented as optional. **Applied**: the cache is off by
   default (`--cache` or `"cache": true`); few-shot already needed an examples
   file, scheduling already went through `sensai-schedule` or `schedule_task`.

In hindsight, if we started again, items 1, 4 and 5 would simply not be built
before the scenario's core worked end to end on a real machine.

## Consequences

- ✅ Every feature left on by default serves a step of Camille's or Marc's day;
  the demo follows one story instead of a catalogue tour.
- ✅ The confidentiality promise becomes consistent: nothing leaves the
  machine unless Marc switches it on.
- ✅ Fewer known defects in the default path (backlog #10, A2 trial finding,
  few-shot vs preference).
- ❌ Less of the catalogue is visible by default; a reader who counts features
  may see fewer of them.
- ❌ Work already done (three visual ADRs, keyword routing, share links) is
  set aside; the time spent on it is not recovered.
- ❌ Running project tests in the sandbox needs the project's dependencies
  installable there (network, time), which the current sandbox forbids by
  design (no network).
- Follow-up: if accepted, one implementation PR per item, each with its
  tests; ADR-0008's status line becomes "Accepted; partly superseded by
  ADR-0056" and this ADR becomes Accepted. If refused, this ADR is marked
  Abandoned and stays as the record of the review.
