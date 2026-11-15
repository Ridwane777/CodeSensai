# ADR-0008 - Scope: implement the 28 features of the catalog

- **Status**: Accepted; partly superseded by ADR-0056 (2026-11-02)
- **Date**: 2026-10-11
- **Deciders**: Fresnel SATIGNON (Workstream A)
- **Workstream**: All

## Context
The CodeSensai catalog (`features_catalog.pdf`) lists 28 features: the
mandatory base [B1] and 27 optional features in six families (Memory,
Tools, RAG, Orchestration, Evaluation, UX). The pre-scope approved at
bootstrap kept 13 of them, 4 of which as bonus, split into workstreams.

The requirement communicated to the team on 2026-10-11 is to implement
**all** the features of the catalog. The 14 features missing from the split
therefore had no owner.

Constraint: the final delivery is on 2026-11-01, i.e. three weeks away, and
the requirements mandate at least two user stories per feature.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Keep the pre-scope (13 features) | Manageable load, controlled integration. Page 1 of the catalog says fewer, well-integrated features are preferred. | Does not meet the requirement given to the team. |
| Pre-scope + a few cheap ★ features (T4, A5, X2) | Quick win, reuses existing code. | Does not meet the requirement either. |
| **All 28 features** | Meets the requirement. Full catalog coverage for the demo. | Double the load: 27 features, at least 54 user stories, in three weeks. Less depth per feature, more integration points. |

## Decision
We implement the 28 features. The 14 missing ones are assigned by
proximity to each workstream's code, and the 4 bonus ones become mandatory:

| Workstream | Added features |
| --- | --- |
| A - Brain | A2 Multi-agents, M2 Token Budgeting, A5 Persona, A7 Prompt optimization |
| B - Hands | EV1 Evaluation and hallucinations, T4 File access, X5 Scheduling |
| C - Memory | R2 Advanced RAG, M3 Structured memory, A6 Semantic cache |
| D - Interface | X2 Branching/interruption, T3 Web search, X3 Export, X4 Questions and forms |

## Consequences
- ✅ Every catalog feature has an owner and a deadline (ClickUp tasks
  created on 2026-10-11, deadlines on 10/18 or 10/25 depending on their
  dependencies).
- ✅ Several additions reuse what exists: T4 builds on the tool gateway
  (ADR-0006), A6 and R2 on the RAG embeddings, M3 on M1's SQLite database.
- ❌ Less time per feature: risk of features that are present but shallow,
  which the catalog says is penalized.
- ❌ The S2 integration milestone (deadline 10/04) is not met: we add load
  while the base building blocks are not yet merged.
- ❌ More dependencies between workstreams (R2/A6/EV1 wait for R1, M2 waits
  for EV3, X2/X4 wait for the event stream and web confirmation).
- Follow-up:
  - get the requirement confirmed in writing at the next check-in;
  - **revision threshold**: if by 10/18 the A, B and C building blocks are
    not merged into `main`, write a new ADR that first removes the features
    least related to the use case (X5 Scheduling, X3 Export, A7 Prompt
    optimization);
  - user stories in `docs/user-stories/`, at least two per feature.
