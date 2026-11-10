# ADR-0043 — Persona (A5): keyword routing, per-persona tool restriction, session-only personas

- **Status**: Accepted; partly superseded by ADR-0056 (2026-11-02: keyword routing and `/persona add` removed, tool restriction kept)
- **Date**: 2026-10-27
- **Deciders**: Fresnel (Workstream A)
- **Workstream**: A (`knowledge/persona.py`, `cli.py`)

## Context

[ADR-0042](0042-configurable-personas.md) shipped the part of [A5] Persona
the catalogue requires: config-driven profiles, switchable mid-session
without losing context. Its "Consequences" section explicitly left three
things for later, without forcing a rewrite of that ADR:

- automatic persona routing (the catalogue's own example: "a support system
  that routes to a technical agent or a commercial agent based on the
  client profile");
- per-persona tool restriction (a persona only changed the system prompt
  text, not what the agent could actually do);
- adding a persona without editing `config.json` by hand.

None of these three are required by the catalogue's wording for A5, but
they make the feature closer to its real-world examples and reuse
infrastructure the repo already has (`ToolPreferences`, the chat-command
pattern).

## Considered options

| Enrichment | Option chosen | Alternative rejected |
| --- | --- | --- |
| Keyword routing | A `keywords` list per persona in config; before each turn, switch if a keyword is found in the question (`auto_route()`) | Embedding-based semantic routing (reusing R1's `bge-m3`): more accurate, but adds a model call to every turn's latency for a feature whose catalogue wording only asks for *a* switch, not *which* trigger decides it; left for later if keyword matching proves too coarse in practice |
| Tool restriction | A persona's `tools.disabled` list is unioned into the existing `ToolPreferences.disabled` (`tools.preferences` reassigned on switch) | A separate permission system per persona: would duplicate `ToolPreferences`/`ToolGateway` logic that already does exactly this job for the global config |
| Session-only personas | `/persona add <id> <name> <role> <tone> <scope>`, kept in memory only (`PersonaStore.add()`) | Persisting added personas to `config.json` or `profile.json`: turns a chat command into a file-writer, and risks a concurrent write racing a hand edit of `config.json` while `sensai` is running; left for later if the need for permanent, chat-created personas is confirmed |

## Decision

- `Persona` gets two optional fields, both empty by default so existing
  configs keep working unchanged: `keywords: tuple[str, ...]` and
  `tools_disabled: frozenset[str]` (from a profile's optional `"keywords"`
  and `"tools": {"disabled": [...]}`).
- `auto_route(user_input, store, active_id)` returns `(persona id, matched
  keyword)` for a persona (other than the active one) with a keyword in the
  question, or `None`. Matching is on **whole words**, ignoring case and
  accents (NFKD folding, `\b`-bounded): the keyword `test` does not fire on
  "latest" or inside a pasted traceback word, and "securite" finds
  "security". The matched keyword is shown in the switch message, so a
  false positive is easy to understand. On a tie between several matching
  personas, the first by alphabetical id wins: simple and deterministic,
  not a ranked search.
- Routing runs once per turn, **before the cache lookup** and before the
  system prompt is rebuilt. A chat command never reaches that point, but a
  question that would be served from the cache does — and it must, because
  the persona a question routes to decides whether the cache may answer it
  at all (see Consequences). A first version routed after the cache read, so
  a question that should have switched to a tool-restricted persona was
  answered from a cache entry produced under the previous, more permissive
  persona (review: PR #95, second pass).
- A switch made by `auto_route` is remembered as automatic: when a later
  question matches no keyword, the CLI goes back to the default persona
  instead of staying on the auto-chosen one for the rest of the session. A
  switch made explicitly with `/persona use` is never undone this way.
- `cli.main()` keeps the *global* `ToolPreferences` from `config.json`
  untouched (`base_tool_preferences`) and only ever **adds** to its
  `disabled` set from the active persona's `tools_disabled`
  (`apply_persona_tools()`, called at startup, after `/persona use`, and
  after an automatic switch). A persona can never re-enable a tool the
  global config disabled — the user's own restrictions stay the floor.
- `/persona add <id> <name> <role> <tone> <scope>` (quoted multi-word
  fields, parsed with `shlex`, matching `chat_commands.py`'s style) adds a
  persona to the in-memory `PersonaStore` for the running session only. The
  command's own reply says so explicitly, so a user doesn't believe it
  survived a restart when it didn't. The `id` must match
  `^[a-z0-9_-]+$` and the four text fields must not be empty, otherwise the
  persona is refused: an id with a space would be accepted but could never
  be selected afterwards (review: PR #95).

## Consequences

- ✅ Reuses `ToolPreferences`/`ToolGateway` exactly as they already work for
  the global config: no new permission model, no new confirmation path.
- ✅ A project that configures no `keywords` or `tools.disabled` sees no
  behavior change at all from this ADR — both are purely additive.
- ❌ Keyword routing matches whole words only: there is no plural handling
  and no stemming, so the keyword `test` does not fire on "tests" or
  "testing" — each variant has to be listed in `keywords`. It is still a
  word list, not a topic classifier: a question that never uses a listed
  word never switches, however clearly it is about the topic. Acceptable
  for a first iteration (the catalogue's own example is similarly coarse:
  "route based on the client profile"), but a real deployment with many
  personas would need either longer keyword lists or the semantic-routing
  alternative rejected above.
- ❌ A persona added with `/persona add` disappears when the CLI restarts.
  If a team wants chat-created personas to persist, this ADR needs a
  follow-up (not a rewrite) once that need is confirmed, not assumed.
- ❌ Not wired into `sensai-schedule` (X5) or the web interface
  (`src/sensai/web/runtime.py`) — same gap ADR-0042 already left for the
  base feature. Neither entry point reads `settings["personas"]`, so a
  team running the web server gets no persona at all, not even the
  default one's name shown in the CLI banner. No tracking issue filed yet
  (review: PR #95) — follow up once the web side of A5 is prioritized.
- ❌ A cached answer (A6) is scoped to `project` and `model`, never to the
  active persona. To avoid a persona's tool restriction being silently
  bypassed by a cache hit produced under a more permissive persona,
  `cli.py` skips the cache entirely (lookup and store) whenever the active
  persona has any `tools_disabled` — simple and safe, but it means a
  tool-restricted persona never benefits from caching at all, even for a
  question its restriction has nothing to do with (review: PR #95). The
  check uses the persona *after* routing (see Decision), so it also covers
  a question that switches persona on this very turn.
