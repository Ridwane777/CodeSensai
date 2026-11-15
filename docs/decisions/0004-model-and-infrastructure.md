# ADR-0004 - Model and infrastructure: qwen3:8b in dev, qwen3-coder:30b on RunPod

Date: 2026-09-22
Workstream: All
Status: accepted - adopts the choice in docs/research/model-choices.md (Meric), approved by the team

## Context
No team machine can run a decent agentic model: the reference setup
([infra-options.md](../research/infra-options.md)) has 4 GB of VRAM, 16 GB
of RAM and 19 GB of free disk. Yet a ReAct loop chains several generations
per conversation turn - what is merely slow in chat becomes unusable when
every tool call costs a full generation.

Meric surveyed the options in two documents:
[infra-options.md](../research/infra-options.md) (free cloud credits (e.g.
Azure), RunPod, hourly costs) and
[model-choices.md](../research/model-choices.md) (BFCL, SWE-bench Verified,
VRAM, hallucination rate, context window, limited to 2025/2026 models). This
ADR does not redo that work: it turns its conclusion into a decision, so that
it applies to the code rather than staying in a document nobody opens.

## Considered options
- **A single model everywhere** - simpler to explain, but either we pick a
  model small enough for the weakest machine (and demo the agent on a model
  that misses its tool calls), or we force everyone onto a paid GPU pod at
  all times, including to write code that never calls the model.
- **Two models, one per use** - chosen.

## Decision
- **Day-to-day development: `qwen3:8b`.** ~5 GB in Q4, fast iteration,
  native tool calling supported by Ollama. It is the default in
  `config.json` and `DEFAULT_MODEL`.
- **Validation and demo: `qwen3-coder:30b`** (Qwen3-Coder-30B-A3B) on a
  RunPod RTX 3090/4090 pod, reached via `--host http://<pod-ip>:11434`. Best
  quality/VRAM ratio on a 24 GB card, agent-oriented, 256K context for long
  chains of tool calls.
- **Second choice to A/B test: `nemotron-3-nano:30b`** - same VRAM tier,
  BFCL score published on the (harder) v4 test, 1M context.
- **Rejected: Gemma 3 27B** (no native tool calling in Ollama),
  **DeepSeek-R1-Distill-Qwen-32B** (trained for reasoning, not tool calling),
  **DeepSeek-V3.2** (671B, out of reach for self-hosting).
- The RunPod pod only runs during test sessions: per-second billing,
  ~$13-20/month at 3 h/day, versus ~$5/day for a pod left running.

## Consequences
- **The Ollama host is no longer assumed to be local.** `--host` and
  `config.json` are the only things to change to switch between the dev
  machine and the pod: not a line of `core/ollama_client.py` moves. This is
  what lets all three workstreams code on `qwen3:8b` without a running pod.
- **Strong constraint on ADR-0003**: the decision to use native Ollama tool
  calling only holds if the configured model supports it. Both chosen models
  do, and that is precisely why Gemma 3 was excluded - the two ADRs say the
  same thing. To be checked at startup rather than letting the agent fail
  mid-session.
- A feature validated on `qwen3:8b` may behave differently on
  `qwen3-coder:30b`. Do not discover the gap the day before the demo: move
  to the pod as soon as the ReAct loop chains two tools.
- The pod is reachable over HTTP on the network: do not expose it without
  filtering; an open Ollama instance is a generation API open to everyone.
