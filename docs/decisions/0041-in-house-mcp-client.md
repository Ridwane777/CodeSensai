# ADR-0041 — MCP (T1): a hand-written stdio client, servers declared in config.json

- **Status**: Accepted (2026-10-24)
- **Date**: 2026-10-24
- **Deciders**: Ridwane (Workstream C) and Christopher (Workstream D)
- **Workstream**: D (`tools/mcp_tool.py`); wired into the CLI, the web server and `config.py`

## Context

[T1] MCP requires the agent to call the tools of an external MCP server. The
file `tools/mcp_tool.py` was only a skeleton ("TODO") wired
nowhere; the full trial run of 2026-10-24 caught it. `docs/dependencies.md`
noted "MCP library: not chosen yet".

Constraints: no framework, the same gateway for all tools
(ADR-0006: an external tool with no declared risk is treated as `execute`), and
the T1 user stories: tools registered at startup without touching
Workstream A code; a broken server does not block the agent.

## Considered options

| Option | Pros | Cons |
| --- | --- | --- |
| Official `mcp` SDK (Python) | All protocol features (stdio, HTTP, resources, prompts); maintained by the authors | Asynchronous (anyio) in synchronous code; about ten dependencies (httpx, pydantic, starlette, sse…) for four messages |
| **Hand-written stdio client** (JSON-RPC 2.0, one line per message: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`) | No dependency; about 200 readable lines; testable with a fake server | stdio transport only (no remote HTTP MCP server); tools only (no resources or prompts); must evolve with the protocol |
| A single generic `mcp_call(tool, arguments)` tool (the skeleton) | A single tool to register | The model sees neither the available tools nor their parameters: it guesses names |

## Decision

Hand-written stdio client (`tools/mcp_tool.py`). Servers are
declared in `config.json`:

```json
"mcp_servers": {
  "time": {"command": "uvx", "args": ["mcp-server-time"], "risk": "read", "timeout_s": 30}
}
```

At startup (CLI and web server), each server is launched; each of its
tools becomes an agent tool, `mcp_<server>_<tool>`, with the
description and parameter schema given by the server. The risk defaults to
`execute` (configurable per server); the confirmation shows the
server, the tool and the arguments; the response goes through the gateway's
guardrails. An invalid configuration stops startup; a server that is
not found, silent, unreadable or crashes produces a warning (or a
tool error during the session), never an exception.

## Consequences

- ✅ T1 works: trial run on the pod, the model calls the MCP tool on
  its own, with confirmation, and the key returned by the server is masked.
- ✅ No new dependency; a new server is plugged in through
  `config.json` alone.
- ✅ Failures are tested: server not found, silent, unreadable response,
  crash during a call.
- ❌ stdio transport only: a remote (HTTP) MCP server is not
  reachable. Move to the official SDK if that need arises.
- ❌ Tools only: MCP resources and prompts are ignored.
- ❌ An MCP server is third-party code launched on the machine, with the
  user's rights and without a sandbox: only add trusted servers
  (risk L8, `docs/legal/`).
- ❌ Not yet tried with a published server: in this session, running
  a downloaded package (`uvx mcp-server-time`) was blocked by the
  development tool's permissions. Trial run done with the repo's test
  server.
- Follow-up: try a published server (`mcp-server-time`,
  `@modelcontextprotocol/server-filesystem`); show MCP tools in
  the web interface (story `T1-tool-calling-mcp.md`).
