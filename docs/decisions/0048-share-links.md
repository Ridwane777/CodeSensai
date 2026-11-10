# ADR-0048 — Export & Publication (X3): share links are random-token snapshots served by `sensai-web`

- **Status**: Accepted (2026-11-01); amended by ADR-0056 (2026-11-02: share links off by default)
- **Date**: 2026-10-29
- **Deciders**: Ridwane (Workstream C), on behalf of Workstream D (Christopher) — to be confirmed by the team
- **Workstream**: D (`web/shares.py`, `web/server.py`, `web/runtime.py`, `frontend/`)

## Context

[X3] Export & Publication asks for exports (JSON, Markdown, PDF) and for "a
public link, without authentication, to view a shared conversation in the
browser". Exports were real (browser files, and `GET /export` filtered by the
EV2 guardrails, [ADR-0024](0024-web-contract-extensions.md)); the share link
was fake: a hash on the reserved domain `codesensei.example` (issue #61).

Constraints: CodeSensai is a local, single-user tool. `sensai-web` listens on
`127.0.0.1` by default and every API route needs a bearer token
([ADR-0023](0023-web-api-access.md)). A conversation can contain code,
paths and secrets. There is no hosting service in the project, and adding one
would mean a new provider, an account and a privacy policy for third-party data.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| **Random token, snapshot stored next to the sessions, read-only page served by `sensai-web`** (chosen) | No new provider; the link opens without the API token; secrets masked once at share time; expiry and revocation | Only reachable by people who can reach the server (same machine by default); the server must be running |
| Publish to an external paste/gist service | A truly public URL | New provider, account and token; conversation data leaves the machine; legal work (`docs/legal/`) for a demo feature |
| Live link to the session (no snapshot) | Always up to date | Everything said after sharing becomes public; a token leak exposes the whole future conversation |
| Encode the conversation in the URL fragment | No storage | URL length limits; no expiry or revocation; the content travels wherever the link is pasted |

## Decision

`POST /api/sessions/{id}/share` (API token required) copies the session's user
and assistant messages, passed through `filter_output`, into
`<data_dir>/shares.json` (mode 600), under the SHA-256 of a
`secrets.token_urlsafe(32)` token, with a 7-day expiry. It returns
`{"url": "/share/<token>", "token", "expires_at"}`: the token is shown once.
`GET /share/<token>` needs no token and returns static HTML (every text
escaped) with `Content-Security-Policy: default-src 'none'` (no scripts),
`noindex`, `no-referrer` and `no-store`. Unknown, revoked and expired links get
the same 404 page. `POST /api/shares/<token>/revoke` deletes a link; expired
links are removed when the server starts. The Export page creates the link on
demand with the real server and keeps the fake one, labelled as such, with the
simulated engine.

## Consequences

- ✅ The link is real, needs no login, and shows only what existed when it was
  shared, with secrets masked.
- ✅ A leaked `shares.json` does not give the links (only their hashes).
- ❌ "Public" is limited to whoever can reach `sensai-web`: by default only this
  machine. Sharing with a colleague means `--bind` on the network, with the
  warning the server already prints; the API stays behind its token, the share
  page does not.
- ❌ Anyone holding the link can read the conversation until it expires or is
  revoked; there is no revoke button in the interface yet (API only).
- ❌ The masking relies on the EV2 patterns: a secret they do not recognise is
  published as is.
- ❌ `shares.json` is rewritten whole on each change: fine for a single user,
  not for many links.
- Follow-up: a "Revoke" button and a list of active links on the Export page;
  revisit the storage if links are ever shared beyond one machine.
