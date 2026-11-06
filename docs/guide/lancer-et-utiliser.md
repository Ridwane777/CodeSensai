# Running and using CodeSensei

Practical guide: install, start the model, chat with the agent.
For feature details, see the [README](../../README.md).

## 1. Prerequisites

- Python 3.12 or later
- [Ollama](https://ollama.com) installed (serves the model)
- Docker (for `run_code` and `web_search`; without Docker, these two tools
  return a clear error, everything else works)

## 2. Installation (one time)

```bash
# Models
ollama pull qwen3:8b        # default dev model
ollama pull bge-m3          # embeddings for project search (~1.2 GB)

# Python environment
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Docker (optional)
docker pull python:3.12-slim                           # execution sandbox
docker build -t sensai-browser:latest docker/browser   # search browser (~12 min)
```

## 3. Start the model

1. **Start Ollama** (if not already running as a service):
   ```bash
   ollama serve        # listens on http://localhost:11434
   ```
2. **Check** that the model is present:
   ```bash
   ollama list
   ```
3. **Launch the agent** from the project folder to analyze:
   ```bash
   source .venv/bin/activate
   sensai
   ```

By default, `sensai` reads `config.json` (`qwen3:8b` on `http://localhost:11434`).

### Choosing another model or server

```bash
sensai --model qwen3-coder:30b
sensai --host https://<pod-id>-11434.proxy.runpod.net --model qwen3-coder:30b
```

`--host` targets a remote Ollama instance (e.g. a RunPod pod): the code
doesn't change, only the config does.

### Connecting an MCP server (T1)

In `config.json`, each MCP server (stdio transport) becomes a set of agent
tools (`mcp_<server>_<tool>`), confirmed like any other
([ADR-0041](../decisions/0041-client-mcp-maison.md)):

```json
"mcp_servers": {
  "time": {"command": "uvx", "args": ["mcp-server-time"], "risk": "read"}
}
```

A server that can't be found or stays silent is reported at startup; the
agent still starts. Only add servers you trust: they run on your machine
with your own permissions.

## 4. Using the agent

Type your question at the `You >` prompt. The agent reasons, calls tools if
needed (each step is shown), then answers.

```
You > Read calcul.py, run it, fix the bug, then verify.
  → read_file({'path': 'calcul.py'})
  → run_code({...})
[Confirmation] The agent wants to use the tool « run_code » (risk: execute) [y/N]
```

**Confirmations.** Any file write or code execution requires an explicit
"yes". An empty answer, Ctrl+C, or end of input all count as a refusal.

### Agent tools

| Tool | What it does |
|---|---|
| `search_codebase` | Searches the project's code and docs (`kind` filter: `code` or `doc`, and `path`: a folder) |
| `read_file` | Reads a file from the current folder (1 MB max) |
| `write_file` | Creates or replaces a file, with diff and confirmation |
| `run_code` | Runs Python in a disposable Docker container |
| `web_search` | Web search from an isolated Chromium |

### Chat commands

| Command | Effect |
|---|---|
| `/remember <text>` | Add a preference to the profile |
| `/profile` | Show the profile |
| `/forget` | Clear preferences |
| `/sessions` | List the project's sessions |
| `/persona` | Show the active persona |
| `/persona list` | List the available personas |
| `/persona use <id>` | Switch persona, without losing the conversation history |

### Personas (A5)

The agent's name, tone, role, and response scope are configurable without
touching the code, in `config.json`:

```json
{
  "personas": {
    "default": "assistant",
    "profiles": [
      {"id": "assistant", "name": "Sensai", "role": "development assistant",
       "tone": "neutral and precise", "scope": "the current project"},
      {"id": "legal", "name": "Master Sensai", "role": "legal assistant",
       "tone": "formal", "scope": "legal matters only, no code",
       "tools": {"disabled": ["run_code"]}},
      {"id": "math-tutor", "name": "Professor Sensai", "role": "mathematics tutor",
       "tone": "pedagogical", "scope": "mathematics only",
       "tools": {"disabled": ["run_code", "web_search"]}}
    ]
  }
}
```

Without a `personas` section, the agent keeps a neutral default persona. See
ADR-0042.

One optional field per profile (ADR-0043):

- `tools`: `disabled` removes tools from what that persona can call, on
  top of whatever `config.json`'s global `tools` section already removes
  — a persona can only restrict further, never loosen the global config.

Keyword routing (`keywords`) and session-only personas (`/persona add`) were
removed on 2026-11-02 (ADR-0056, item 4): a `keywords` field now stops the
program with a message. Switch persona with `/persona use <id>` or the web's
"Agent actif" selector.

### Automatic few-shot examples (A7)

A small library of good examples (question + answer, same JSONL format as
`sensai-eval`'s datasets) can be attached automatically to a question close
enough to one of them:

```json
{
  "fewshot_examples": "datasets/examples/dev.jsonl",
  "fewshot_min_score": 0.75
}
```

Each line needs `id`, `question` and `answer` (`eval/dataset.py`'s format —
an existing EV1 dataset works as-is, provided its cases have an `answer`).
Without `fewshot_examples`, nothing changes. The `0.75` threshold is an
**estimate, not a measured value** (see ADR-0044; `scripts/bench_fewshot.py`
measures it, but has not been run yet).

### Token budget and sliding-window summary (M2)

On by default: once the estimated size of what would be sent to the model
crosses a budget, the oldest turns of the conversation are condensed into
one summary (by the chat model itself, in a separate call) before the next
question is sent. The most recent turns are always kept exact, and nothing
saved to the session (M1) is ever rewritten — resuming later still shows
the full, uncompressed history.

```json
{
  "num_ctx": 8192,
  "token_budget": true,
  "token_budget_keep_recent": 6
}
```

`num_ctx` is the context window sent to Ollama with every chat call (the
CLI, the web server, `/structured`, sub-agents, scheduled tasks and
`sensai-eval`); without it Ollama truncates at its own default (2048 or 4096
tokens), silently. The budget (`token_budget_max`) defaults to `num_ctx` minus
2000 tokens kept for the answer, so `--num-ctx` moves it too; set
`token_budget_max` yourself only to summarize earlier, and keep it under
`num_ctx`. A turn that is over budget but cannot be summarized (one very
large message) is sent as is, with a warning.

`--no-token-budget` disables the summary entirely. See ADR-0045 — the token
count is an approximation (`len // 4`), not a real tokenizer, and the default
`8192` window is an estimate, not a measured value (a larger window costs GPU
memory and latency).

### Generation parameters and loop limit (ADR-0057)

```json
{
  "generation": {"temperature": 0.2, "top_p": 0.9, "seed": 42},
  "max_iterations": 6
}
```

`generation` accepts `temperature`, `top_p`, `top_k`, `seed`, `num_predict` and
`repeat_penalty`; they are sent in `options` with every chat call, next to
`num_ctx`. Without the section, the defaults are `temperature` 0.2 and `top_p`
0.9; any other key stops the program (a misspelt setting must not look
active). `max_iterations` (1 to 50, default 6) is the number of model calls a
turn may make before it stops. The EV1 judge and the R2 re-ranker keep their
own temperature of 0. `/context` shows what is actually sent. Measurement of
these settings: [generation-parameters.md](../performance/generation-parameters.md).

### Running on a laptop without a GPU

On CPU, `qwen3:8b` reads the system prompt and the tools before its first
word: one ordinary question takes **7 to 11 minutes** on the team laptop
([trial of 2026-11-06](../performance/essais/essai-2026-11-06.md)). Two
settings matter:

```json
{
  "request_timeout": 1800,
  "tools": {"tool_timeout_s": 1800, "delegation_timeout_s": 1800}
}
```

- `request_timeout` (or `--request-timeout`): seconds to wait for Ollama's
  answer, **600 by default**; the connection itself still fails after 10 s, so
  a stopped Ollama is reported at once.
- `delegation_timeout_s`: how long a sub-agent (`delegate_task`, `team_task`)
  may run, **120 s by default**; `tool_timeout_s` (120 s) caps every tool call,
  so raise both.

Even with these settings, `qwen3:8b` does not complete `team_task` (A2) and
gave a wrong structured answer (T5) in that trial: use `qwen3-coder:30b` on a
24 GB GPU for those.

### Useful options

| Option | Effect |
|---|---|
| `--model`, `--host` | Ollama model and server |
| `--session <id>` | Resume a specific session |
| `--new-session` | Start over with an empty session |
| `--retention-days N` | Session retention period (default 30, 0 = forever) |
| `--no-rag` | Disable project search |
| `--rag-top-k N` | Passages attached per question (default 5) |
| `--rag-min-score X` | Relevance threshold (default 0.54) |
| `--no-rag-rerank` | Skip reranking passages with the model (about 3 s less per question, R2) |
| `--cache` / `--no-cache` | Serve and record cached answers (A6), off by default since ADR-0056; in chat: `/cache`, `/cache clear`, `/again` |
| `--fewshot-examples <file>` | JSONL example library for automatic few-shot (A7) |
| `--fewshot-min-score X` | Relevance threshold for a few-shot match (default 0.75 — estimate, see ADR-0044) |
| `--no-token-budget` | Send the full history to the model, never summarizing old turns (M2) |
| `--num-ctx N` | Context window sent to Ollama (default 8192 — estimate, see ADR-0045) |
| `--temperature T`, `--top-p P`, `--seed N`, `--num-predict N` | Generation parameters sent to Ollama, override `generation` in config.json (ADR-0057) |
| `--max-iterations N` | Model calls allowed per turn (default 6) |
| `--token-budget-max N` | Estimated tokens above which old turns are summarized (default: `--num-ctx` minus 2000) |
| `--token-budget-keep-recent N` | Recent turns always kept exact, never summarized (default 6) |
| `--system-prompt <file>` | Try a test system prompt |
| `--data-dir <folder>` | Data folder (default `~/.sensai`) |

Full list: `sensai --help`.

## 5. Other commands

```bash
sensai-schedule add daily-summary --every 1d --prompt "Summarize the project's TODOs."
sensai-schedule run-due        # run due tasks (for cron)
sensai-prompt history system   # prompt versions
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out report.json
```

## 6. Troubleshooting

| Symptom | Lead |
|---|---|
| Connection error | Ollama isn't running: `ollama serve`, or check `--host` |
| Model not found | `ollama pull <model>` |
| `run_code` / `web_search` fail | Docker missing or images not built (step 2) |
| Unknown key in `config.json` | Inside a section (`tools`, `generation`…) the CLI deliberately stops: fix the key. An unknown **top-level** key is still ignored silently ([trial of 2026-11-06](../performance/essais/essai-2026-11-06.md)) |
| "Ollama ne répond pas (timeout de … s)" | Slow model on CPU: raise `request_timeout` (see "Running on a laptop without a GPU") |
| First question is slow | Project indexing (bge-m3); later ones are incremental |

## 7. Tests

```bash
pytest
ruff check .
```
