# ADR-0055 — Prompt versions (A4) in the web: read the registry, try a version in one conversation

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C), on behalf of Lot A (Fresnel) — to be confirmed by the team
- **Lot concerned**: A/A4 (feature presented by Lot A; registry `knowledge/prompt_versions.py` from [ADR-0010](0010-versionnement-des-prompts.md)), D (`web/runtime.py`, `web/server.py`, `frontend/`)

## Context

Prompt versions (A4) live in `prompts/versions.json` with immutable files per
version; `sensai-prompt` lists, compares, saves and moves the "active"
bookmark ([ADR-0010](0010-versionnement-des-prompts.md)). The web Prompts page
showed demo data: v2 was a fake draft and "Mettre en service" changed nothing.
The registry is a file of the repository, committed and checked by CI
(`sensai-prompt check`); moving the bookmark changes the prompt for every user
of the repo.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep the demo page | Nothing to build | The page shows invented versions next to a real feature |
| (a) Read-only registry | No risk to the registry | Cannot see the effect of a version without the terminal |
| **(b) Read-only registry + "try this version in this conversation"** (chosen) | Compare versions on a real conversation; the registry is never written | The trial is lost when the server stops; only the system prompt |
| (c) Also "activate" from the web (`PromptStore.use`) | Feature parity with `sensai-prompt use` | A browser click would change a committed file for the whole team, without review |

## Decision

- Read-only routes (token required): `GET /api/prompts` (each prompt, its
  active version and its versions: id, date, author, description, active),
  `GET /api/prompts/{name}/{version}` (text), `GET /api/prompts/{name}/diff?a=&b=`
  (unified diff from `PromptStore.diff`). 404 on an unknown prompt or version.
- `GET`/`POST /api/sessions/{id}/prompt-trial` `{"version": "v2"}` (system
  prompt only): the next turns of that conversation use that version's text
  instead of the system prompt loaded at startup; `{"version": null}` goes back.
  Held in server memory only; 404 unknown version; 409 while a turn runs.
  Sub-agents of that conversation get the same text.
- A turn under trial neither reads nor writes the answer cache: an answer
  stored under another prompt says nothing about the one being tried.
- The web server never calls `PromptStore.save` or `use`; a test checks that
  every file of the registry has the same bytes after listing, diffing, trying
  and going back. Activating a version for everyone stays `sensai-prompt use`.

## Consequences

- ✅ The Prompts page shows the real registry; "Essayer dans cette
  conversation" and the chat badge "prompt system vN (essai)" make a version
  testable without a terminal and without touching the repo.
- ✅ No path from the browser to a committed file.
- ❌ The trial is not saved: lost when `sensai-web` stops, not restored when a
  conversation is reopened afterwards.
- ❌ Only the system prompt can be tried; memory and judge versions are
  readable but not tried.
- ❌ If `sensai-web` was started with an explicit `--system-prompt` file, going
  back from a trial returns to that file, while the page labels the registry's
  active version as "en service".
- ❌ Not yet tried with the real model (tested with pytest and vitest only).
