# ADR-0023 - Web API access: token, local listening, a single public access

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D (affects B for the secret filters, and the legal side)

## Context
Written **after** the user stories [US-WEB-11, 13, 14 and 16](../architecture/web-api.md). Exposing the agent on the web
means exposing **code execution**: [ADR-0005](0005-web-interface-facade.md) and Workstream A's contract require
authentication, but `web-api.md` leaves it "to be implemented by Workstream D" with no mechanism. It must be
chosen, with one exception to handle: feature X3 requires a **public, account-free** share link.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| No authentication, local listening only | Simplest | Refused by Workstream A's contract: any local program, or any page open in the developer's browser, can drive the agent |
| Account and password, cookie sessions | Familiar, several users | A whole account system to write and protect (password storage, cookies, CSRF) for an individual tool |
| OAuth / SSO | Delegates identity | Dependency on an external provider, unusable offline, oversized |
| **Bearer token generated at startup, local listening by default, closed list of allowed origins** | Simple, verifiable, suited to individual use; no stored secret | A single user; see the drawbacks |

## Decision
1. At startup, the server generates a **random token** (32 bytes), prints it **once** in the console and never writes it to a file, a log or a URL. Every API route, streams included, requires it in the `Authorization: Bearer` header.
2. The comparison is constant-time; a missing, wrong or malformed token gets the **same** `401` response.
3. The server listens on **the local machine only**. Opening it to the network requires an explicit option and a warning.
4. Allowed origins (CORS) are **a closed list**; never `*`. The interactive API documentation is disabled.
5. `GET /api/health` is the only route without a token, and says nothing beyond "ok".
6. `GET /api/config` never returns an Ollama address, a token or a path.
7. **Only exception: the share link** (X3). Disabled by default, explicitly requested, **opaque token distinct from the session identifier**, read-only, revocable, with an announced expiry, content filtered of secrets like the stream.

## Consequences
- ✅ No one drives the agent without the token, even from another tab or another program on the same machine, as long as the token has not leaked.
- ✅ The server stores no secret; the public surface is limited to a health route and explicitly created share links.
- ❌ **A single user**, no accounts or roles. Several people on the same server would require real authentication.
- ❌ **The token is printed in the console and lost on every restart**: the user must copy it again. The browser must keep it in memory, which exposes it to a malicious script injected into the page.
- ❌ **Local listening does not protect against other users of the same machine** or programs already running on it.
- ❌ **No rate limiting**: a 32-byte token cannot be guessed, but nothing prevents flooding the server.
- ❌ **The share link is public by design**: anyone who receives it can read the session. This is a personal-data risk, to be handled in the legal documents; secret filtering reduces the risk without removing it.
- ❌ **Text written by the model is not filtered**: the gateway only sees tools. If the model copies a secret into its answer, it appears in the stream, the export and the share. Residual risk, to be handled with Workstream B.
- Follow-up: test 401 on every route (done for the prototype); update `docs/legal/` for sharing. **Revision threshold**: as soon as a second person must use the same server.
