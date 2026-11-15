# ADR-0012 - Disposable Docker containers for code execution and web search

Date: 2026-10-12
Workstream: B
Status: accepted; partly superseded by ADR-0013 (choice of search engine)

## Context
The agent must run code it wrote (T2) and look things up on the web. Both are
dangerous in different ways. Model-written code can loop, exhaust memory, delete
files or read secrets. A web page is hostile input parsed by a very large engine,
and a search result is text a stranger wrote.

The earlier prototype (branch `feat/sandbox-execution`) already ran Python in
Docker. It was a separate package, with its own MCP server and pre-execution
hooks, written before the tool gateway existed.

## Options considered
- **Isolated subprocess** - fast and needs only Python, but cannot block the
  network or hide files without extra work (namespaces, seccomp). Protects
  against accidents, not against a determined attacker.
- **Docker container per call** - strong isolation, network off by default,
  resource limits built in. Needs Docker on every machine that runs the demo and
  costs about a second per call.
- **gVisor / Firecracker** - stronger still, but heavier to install than the
  project needs.
- **Web search by HTTP request (`requests`)** - simple, but it parses hostile
  HTML inside the agent's own process, with the user's network and files in reach.
- **Web search through a Chromium container** - a larger image, but a browser
  exploit lands in a disposable unprivileged container, and only plain strings
  leave it.

## Decision
Docker, one fresh container per call, for both.

- Python code runs in `python:3.12-slim` with **no network**.
- Web search runs in a Chromium container (`docker/browser`) that can resolve
  only the search engine, with JavaScript off; its output is parsed on the host
  into bounded plain results. Code and browser never share a container.
- The sandboxes only produce data. Confirmation, credential masking, sanitizing
  and limits stay in the tool gateway (ADR-0006), so the earlier prototype's
  pre-execution hooks and MCP server are not carried over.

## Consequences
- Positive: the A3 criterion "code never runs without explicit confirmation" is
  enforced by the gateway (`execute` cannot be loosened), and the sandbox cannot
  reach the network or the host's files even if that check were bypassed.
- Positive: both tools follow the same contract as any other tool, with the same
  errors and the same output hardening.
- Negative: Docker is required, and the Chromium image (about 1 GB) must be built
  locally once. Without it, `web_search` reports `ImageMissing` and nothing else
  breaks.
- Negative: the browser runs with `--no-sandbox` and outbound network. Residual
  risks, and an optional host firewall rule, are listed in `docs/architecture/sandbox.md`.
- Negative: the search parser depends on one engine's page layout and may need
  updating when it changes.
