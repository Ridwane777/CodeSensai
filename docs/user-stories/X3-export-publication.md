# User stories — [X3] Export and publication

Interface: `frontend/`.

CodeSensai scenario: Camille takes over a Python project and wants to follow,
correct and keep a record of what the agent does, without reading the code.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-simulated-web-interface.md)).
On 2026-10-18, the interface was connected to the real agent through `sensai-web`
([ADR-0035](../decisions/0035-real-web-server.md)) and tried in a browser
with `qwen3-coder:30b` ([real-web.md](../performance/real-web.md)). Each story
carries its status:
✅ checked with the real agent · ◐ partly · 🎭 still simulated · ⏳ not checked yet.
Detail per function: [simulated-vs-real.md](../architecture/web/simulated-vs-real.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories of the interface: [README.md](README.md).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: export and share link with `share_links` on: ✅ with both set-ups.

## US-X3-1 — Keep a record of the session
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ◐ Partly. The Markdown preview contains the real conversation and its tool calls (checked). The JSON, Markdown and PDF files are produced by the browser from what is displayed, and have not been downloaded with the real agent. The server also offers an export with secrets filtered out (`/export`), which the interface does not use yet.

**As** Camille, the developer who must report on her work,
**I want** to export the conversation and the tracking document as JSON, Markdown or PDF,
**so that** I can archive it or pass it on.

**Acceptance criteria:**
- The JSON and Markdown buttons download a file; PDF opens the browser's print view.
- The JSON contains the messages, the reasoning steps and the tracking document.
- An export of an empty conversation gives valid files, without error.
- A preview of the Markdown is visible before the export.

## US-X3-2 — Share the session through a link
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** 🎭 Simulated: the share link stays fake, and the interface says so.
>
> **Update on 2026-10-29:** ◐ Real with the server ([ADR-0048](../decisions/0048-share-links.md)). "Create a share link" on the Export page publishes a read-only copy of the conversation, secrets masked, at `/share/<token>`: no API token needed to open it, valid 7 days, revocable (`POST /api/shares/<token>/revoke`, "Revoke the link" button since 2026-10-31). Checked by the server tests (`tests/web/test_shares.py`) and the frontend tests; not yet opened in a browser with the real agent. The link only works for people who can reach the `sensai-web` server, which listens on this machine only by default. Without the server (simulated engine), the link stays fake and the page says so.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/trials/trial-2026-11-01.md)): the public page was read without a token (CSP `default-src 'none'`), and returned 404 after "Revoke the link".

> **Update on 2026-11-03:** share links are now **off by default** ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 2). The repository's `config.json` has no `share_links` key, which counts as `false`: checked with `sensai-web`, `POST /api/sessions/{id}/share` answers **403** `SHARE_DISABLED` (401 without the API token) ([trial 2026-11-03](../performance/trials/trial-2026-11-03.md)). Marc turns them on by adding `"share_links": true` to `config.json` and restarting `sensai-web`.

**As** Camille, the developer who wants to show her work to a colleague,
**I want** to get a viewing link,
**so that** they can read the session in a browser without an account.

**Acceptance criteria:**
- A link is shown and can be copied.
- (simulated engine) The same content always gives the same link; different content gives another link.
- (simulated engine) **In the demo, the link is simulated** (fake domain `codesensei.example`) and the interface says so explicitly: no public page is created.
- Limit to handle with the real backend: a link without authentication exposes the content of the session (see the risk analysis in `docs/legal/`). With the real server: secrets masked, 7-day expiry, revocation by the API ([ADR-0048](../decisions/0048-share-links.md)).
- With the real server, the link opens a read-only page without logging in; secrets are masked and nothing said after the share appears.
- A revoked, expired or unknown link shows the same "Lien indisponible" page.


---

## US-X3-3 — Export the session from the server, secrets masked
> **Update on 2026-11-06:** scenario step **S9**, hand-over to Marc ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Update on 2026-11-01:** ✅ checked with the real agent.

**As** Camille, who must attach the session to her report for Marc,
**I want** to download the conversation as JSON or Markdown built by the server, with secrets masked,
**so that** the file I hand over contains no key or password, even one the model repeated.

**Acceptance criteria:**
- `GET /api/sessions/{id}/export?format=json` returns the conversation as JSON; `format=md` returns `text/markdown` with one section per message ("## Vous"…); any other format is refused with `400`.
- A password or an API key typed in the chat or written by the model does not appear in either file; `[REDACTED…]` does.
- With the real server, the Export page's JSON and Markdown buttons use this route; with no message yet, the page says there is nothing to export.

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-X3-1 | ◐ | `frontend/src/pages/Export.tsx`, `web/server.py` (`/export`) | `frontend/tests/export.test.tsx`, `tests/web/test_server.py::test_export_filters_secrets` | The JSON/Markdown files are built by the browser from what is displayed; no test downloads them with the real server |
| US-X3-3 Server export (new) | ✅ | `web/server.py` (`/export`), `frontend/src/engine/httpEngine.ts` (`exportSession`), `frontend/src/pages/Export.tsx` | `tests/web/test_server.py::test_export_filters_secrets`, `frontend/tests/httpEngine.test.ts` (export with no session, then `export?format=md`), `frontend/tests/export.test.tsx` |  |
| US-X3-2 | ✅ | `web/shares.py` | `tests/web/test_shares.py` (`le_lien_ouvre_une_copie_filtree_sans_jeton_d_api`, `revoquer_ferme_le_lien`, `un_lien_inconnu_donne_la_meme_page_qu_un_lien_revoque`) |  |
