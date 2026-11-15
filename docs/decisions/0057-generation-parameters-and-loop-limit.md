# ADR-0057 - Generation parameters and loop limit come from the configuration

- **Status**: Accepted (2026-11-02, decided by Ridwane, Lot C)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Lot C)
- **Lot concerned**: All (every call to the chat model)

## Context

No generation parameter was sent to Ollama: neither temperature nor context
size, neither in the code nor in config.json, and no parameter trial existed.
The maximum number of loop steps (6) was hard-coded, and no generation setting
went through the configuration.

Since then `num_ctx` is sent on every call (ADR-0045), but the sampling settings
were still the model's own, decided by whoever packaged it, and the step limit
was the constant `MAX_ITERATIONS = 6` in `core/agent.py`.

Every chat call (agent loop, structured output, sliding summary, `stream_chat`)
goes through `stream_chat_messages` in `core/ollama_client.py`. The EV1 judge and
the R2 re-ranker make their own calls with a temperature of 0, on purpose:
their scores must be reproducible.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Keep the model's defaults | nothing to maintain; the model's packager tuned them | not visible, not reproducible, changes when the model is updated |
| Pass the settings as parameters through every call | explicit, no shared state | about fifteen call sites (CLI, web, scheduler, sub-agents, summary, structured output…) to change, each a chance to forget one |
| **Set them once at start-up in the client, merged into every call's `options`; values in `config.json` (`generation`) and on the command line** | one place, cannot be forgotten by a new call site; an option given by a call (`num_ctx`, a temperature of 0) still wins | module-level state: tests must reset it (`tests/conftest.py` does) |

## Decision

- `config.json` gains a `generation` section with `temperature`, `top_p`,
  `top_k`, `seed`, `num_predict` and `repeat_penalty`; `--temperature`,
  `--top-p`, `--seed` and `--num-predict` override it. An unknown key stops the
  program, like the `tools` and `files` sections: a misspelt setting must not
  look active.
- Default: `temperature` 0.2, `top_p` 0.9 (`DEFAULT_GENERATION` in
  `config.py`). A coding assistant should give the same command, path and tool
  call from one try to the next. Measured on 2026-11-01
  ([generation-parameters.md](../performance/generation-parameters.md),
  `scripts/bench_generation.py`, `qwen3-coder:30b`): all five settings tried
  answered the six questions right, but only `temperature` 0 and 0.2 gave the
  same answer at every try (6/6 questions, against 4/6 for the model's own
  defaults, 0.7 and 1.0), at the same speed (about 119 tokens/s). 0.2 is kept
  rather than 0: same stability, a little room for the model to rephrase.
  A harder set of 22 questions, with its checks committed before the run
  (2026-11-02), gave the same accuracy for every setting (91 %, the two misses
  being right answers in LaTeX notation) and 22/22 stable questions at 0
  against 21/22 at 0.2, 17–18/22 otherwise. 0.2 is kept; switching to 0 would
  gain one question of stability in three runs.
- `max_iterations` (config.json) and `--max-iterations` replace the hard-coded
  6, between 1 and 50; the default stays 6. `sensai-schedule` and `sensai-eval`
  read the same keys from `config.json`.
- `/context` (ADR-0058) shows the settings actually sent.

## Consequences

- ✅ Every call sends explicit, visible, versioned settings; a trial can be
  replayed with a fixed `seed`.
- ✅ One place to change them, for the CLI, the web server, the scheduler and
  the sub-agents.
- ❌ We override the sampling tuned by the model's packager: a lower
  temperature can make answers more repetitive or less inventive; the defaults
  are only worth what the measurement shows.
- ❌ The settings are global to the process: two conversations of the same web
  server cannot use different temperatures.
- ❌ The judge and the re-ranker keep their own fixed temperature, so the
  `generation` section does not apply to them; this is intentional but must be
  known.
- Follow-up: `tests/core/test_ollama_client.py`, `tests/test_config.py`,
  `tests/core/test_agent.py` (`test_the_step_count_is_configurable`); revisit the
  defaults if a model update changes the measured accuracy.
