# ADR-0054 — Personas (A5) in the web: one persona per conversation, held in server memory

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C), on behalf of Lot A (Fresnel) — to be confirmed by the team
- **Lot concerned**: A/A5 (`knowledge/persona.py`, feature owner), D (`web/runtime.py`, `web/server.py`, `frontend/`)

## Context

Personas (A5, Lot A) work in the CLI: profiles read from `config.json`
([ADR-0042](0042-configurable-personas.md)), switched with `/persona use`,
with keyword routing, per-persona disabled tools and session-only personas
([ADR-0043](0043-persona-enhancements.md)). The web server did not read them:
the "Agent actif" selector only changed the displayed name, and it was hidden
with the real server on 2026-10-31. The web runtime serves several
conversations at once, while the CLI has a single one per process, so "the
active persona" has to be attached to something.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep personas CLI-only | Nothing to build | The web keeps a selector that does nothing; A5 cannot be shown in the interface |
| One persona for the whole server | Simplest (one variable) | Switching in one tab changes every open conversation |
| **One persona per conversation, in server memory** (chosen) | Same model as the CLI (a label held in memory, history untouched); conversations are independent | Lost when `sensai-web` stops; not restored from the database |
| One persona per conversation, saved in `sessions.db` | Survives a restart | Schema change shared with the CLI (M1); the CLI does not save it either, the two would diverge |
| Full A5 in the web (creation, keyword routing) | Feature parity | More surface (forms, announcements of automatic switches) for a feature already demonstrated in the CLI |

## Decision

- `WebRuntime` keeps `session_id → persona id` in memory. Default: the
  config's default persona. Deleting a conversation forgets it; a new
  conversation starts from the default.
- Routes (token required): `GET /api/personas`,
  `GET /api/sessions/{id}/persona`, `POST /api/sessions/{id}/persona`
  (404 `PERSONA_NOT_FOUND`, 409 `TURN_IN_PROGRESS` while a turn runs in that
  conversation).
- The turn reuses the CLI's pieces, not a copy: the persona block is
  `Persona.as_prompt()` inserted at the same place as in the CLI; the
  persona's `tools_disabled` is added to the base `ToolPreferences` (never
  removed from it); `delegate_task` / `team_task` get the same gateway and a
  `system_prompt` callable that includes the persona, so sub-agents are bound
  by the same restriction. The answer cache is neither read nor written when
  the persona disables tools (same rule as the CLI).
- Out of scope, kept CLI-only: creating a persona (`/persona add`) and keyword
  auto-routing.

## Consequences

- ✅ The selector and the Agents page show the real personas and their
  disabled tools; switching takes effect at the next turn of that conversation.
- ✅ A restrictive persona is enforced by the gateway for the main agent and its
  sub-agents, tested with a scripted model (pytest).
- ✅ The web prompt now contains the persona block like the CLI's (the default
  persona included).
- ❌ The choice is not saved: reopening a conversation after a `sensai-web`
  restart gives the default persona (same as the CLI, which does not save it).
- ❌ A branch (X2) is a new server session, so it starts with the default
  persona.
- ❌ Keyword routing and persona creation exist only in the CLI; the web
  shows a subset of A5.
- ❌ Not yet tried with the real model (tested with pytest and vitest only).
