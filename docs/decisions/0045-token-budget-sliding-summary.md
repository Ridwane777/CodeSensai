# ADR-0045 — Token Budgeting & Semantic Compression (M2): num_ctx sent explicitly, budget counted on what's actually sent, summary folded into the system message

- **Status**: Accepted
- **Date**: 2026-10-27
- **Deciders**: Fresnel (Lot A)
- **Lot concerned**: A (`knowledge/compression.py`, `cli.py`, `config.py`, `core/agent.py`, `core/ollama_client.py`, `core/structured.py`), D (`web/runtime.py`)

## Context

[M2] Token Budgeting & Semantic Compression asks to count token consumption
per turn against a budget, and, approaching the cap, trigger a sliding-
window summarization pass that condenses the oldest turns into a compact
block while preserving critical facts. Real-world examples given: Claude
Projects summarizing older exchanges, a support system condensing a long
ticket's history.

This is explicitly in tension with [M1] Session Persistence
([ADR-0007](0007-session-persistence.md)), which states "the agent has
access to all past history (no arbitrary limit)" when a session is resumed.
M2 only concerns what is *sent to the model on a given turn*, never what is
*kept in the saved session* — the two don't actually conflict once that
boundary is drawn clearly, but it has to be drawn deliberately, since
`History.turns` (`core/history.py`) is both at once today: what gets sent
(via `as_messages()`) and what gets saved (`SessionStore.save`, M1).

Constraints from the repo: no LLM framework (ADR-0001), so no token-counting
library tied to a specific model's tokenizer; Ollama's HTTP API is the only
source of truth for what the model actually received, and it doesn't expose
a cheap pre-call token count.

**A first version of this ADR shipped without sending `num_ctx` to Ollama at
all** (review: PR #97). Without it, Ollama keeps its own default context
window (2048 or 4096 tokens depending on the version) and truncates silently
*before* M2's budget — set at 8000 tokens — ever gets a chance to act: the
whole feature was a no-op against the real failure mode it exists to
prevent. The second revision sent it from the CLI's main loop and the
summarization call, and the second review pass found that still incomplete:

- `--num-ctx` did not move the budget (the default was computed before the
  command line was read), so `--num-ctx 4096` left a budget larger than the
  window;
- a second, contradictory default (`DEFAULT_MAX_TOKENS = 8000`) lived next to
  the 6192 of `config.py`;
- `num_ctx` was still missing from `/structured`, the `stream_chat` wrapper,
  `sensai-eval`, the sub-agents, the reranker, the web server and
  `sensai-schedule`, and the budget itself was absent from the web server.

This revision fixes those, on top of the ordering and role-alternation fixes
of the previous one.

## Options considered

| Decision point | Option chosen | Alternative rejected |
| --- | --- | --- |
| Counting tokens | A rough `len(text) // 4` estimate (`count_tokens`) | A real tokenizer (`tiktoken`, or a model-specific one): `tiktoken` targets OpenAI's models, not qwen3's, so its count would be wrong for the model actually in use; asking Ollama itself to tokenize would cost an extra HTTP round-trip just to decide whether to compress, before even compressing |
| Producing the summary | One extra call to the same chat model, no tools (`summarize()`, same shape as `/structured`'s one-shot call in `core/structured.py`) | A separate, smaller summarization model: another model to pull, configure and keep working — no measured gain over asking the model already in use, which already understands the project's vocabulary from the conversation itself |
| What gets compressed | Only the messages about to be **sent** this turn (`compress_messages()`), called **after** RAG passages and the A7 few-shot example are attached to the current question — not before | Compressing right after `history.as_messages()`, before that attachment: this was the first version's actual bug (review: PR #97) — a question that's small by itself but carries a large RAG passage would be measured without it, so the budget could be silently exceeded by exactly the content M2 is supposed to account for |
| Where the cut falls | On an even boundary of the turn list (turns are added in `user`, `assistant` pairs), so the kept part always starts on a `user` turn | Cutting at an arbitrary token offset mid-turn: would leave a dangling `assistant` message with no matching `user` message right after, confusing about which question it responds to |
| How the summary is attached | Folded into the **system** message's own content, as an appended note | A synthetic extra `user`-role turn ahead of the kept turns: this was the first version's second bug (review: PR #97) — it produced two consecutive `user` messages (the synthetic one, then the first kept turn when the cut landed right before another `user` turn), breaking the strict alternation Ollama's chat API expects, while this ADR's first revision incorrectly claimed alternation was preserved |
| Context window sent to Ollama | `options.num_ctx`, explicit on **every** chat call the project makes (list in Decision) | Leaving Ollama's own default: this was the first version's most serious bug (review: PR #97) — see Context above |
| Default budget | Derived from the **parsed** `num_ctx` minus a response margin (`resolve_budget()`, `get_settings()`); one rule for the CLI, the web server and `compress_messages()` | A fixed constant, or a default computed from `config.json` before the command line is read: both let `--num-ctx` and the budget disagree (review: PR #97, second pass) |

## Decision

`knowledge/compression.py` owns the whole rule. `DEFAULT_NUM_CTX = 8192` and
`RESPONSE_MARGIN_TOKENS = 2000` live there; `budget_from_num_ctx(num_ctx)` is
their difference, and `resolve_budget(max_tokens, num_ctx)` is the single
place that decides the budget to apply (an explicit `max_tokens`, else
derived from `num_ctx`). `compress_messages(host, model, messages, max_tokens,
keep_recent, num_ctx)` is called **after** RAG and few-shot have been attached
to the current question — both land in `recent` regardless, since
`keep_recent` only ever cuts *older* turns, so this ordering only changes what
the token count actually measures, never what a normal turn receives.

`get_settings()` reads `--num-ctx` (and `num_ctx` in `config.json`), then —
**after** parsing — sets `token_budget_max` to `budget_from_num_ctx(num_ctx)`
unless it was set explicitly (command line or `config.json`). An explicit
budget at least as large as `num_ctx` is refused at startup: it could never
fire before Ollama truncates.

Under the budget, or with too few old turns to summarize without breaking
alternation, `messages` returns unchanged. Otherwise the system message and
the last `keep_recent` turns stay intact, and everything older is replaced by
one call to `summarize()` (same one-shot, no-tools shape as T5's
`/structured`), whose result is appended to the **system** message's content
— never inserted as an extra `user` turn — so the kept turns' own alternation
is never disturbed. `summarize()`'s own input is bounded to what `num_ctx`
(minus the response margin) can hold, truncating the oldest part further if
the turns being summarized are themselves larger than that — otherwise
summarizing an already-huge backlog would just get truncated by Ollama in
turn.

When nothing can be summarized *and* the turn is still over budget (a last
message inflated by RAG on its own, or fewer turns than `keep_recent`), the
messages go out unchanged but the user is told: a warning in the CLI
(`exceeds_budget()`), a notice in the web interface. Silent truncation by
Ollama is the failure M2 exists to prevent; an irreducible turn at least no
longer fails without a word.

`num_ctx` is now sent as `options.num_ctx` on every path that talks to
Ollama's chat endpoint:

- the CLI's main loop (`run_agent_turn(..., num_ctx=)`) and its
  summarization call;
- `/structured` (`run_structured_query`), and the `stream_chat` wrapper;
- the sub-agents of `delegate_task` / `team_task` (`DelegateTool(...,
  num_ctx=)`);
- the R2 reranker (`LlmReranker`) and the model warm-up (`preload_model`, so
  Ollama doesn't reload the model when the first request's window differs);
- `sensai-eval` (generator and EV1 judge) and `sensai-schedule`, which read
  `num_ctx` from `config.json` themselves (`num_ctx_from_config()`);
- the web server (`WebRuntime`), which also applies the budget itself
  (`_within_budget()`, same `compress_messages()` call as the CLI, same
  guarantee that only the copy sent to the model is compacted and the saved
  session is never touched). A summarization failure becomes an interface
  notice, once, never a lost history.

Enabled by default (`token_budget: true`), since the catalogue asks for
this to trigger automatically "as you approach the cap" — a team can turn
it off (`--no-token-budget` / `"token_budget": false`) the same way RAG or
the cache can be.

A failed summary (`CompressionError`: Ollama unreachable, or an empty
response) is never silently swallowed into losing history: the CLI warns and
the web server posts a notice, and the turns go out uncompressed for that
question, exactly like a RAG or cache failure degrades to "the feature
didn't help this time", never to "the agent now knows less than it did".

## Consequences

- ✅ `History.turns` and the saved session stay exactly as rich as before
  this ADR: M1's "no arbitrary limit" promise for a resumed session is
  kept to the letter, because M2 never touches what gets saved.
- ✅ No new dependency, no second model to configure: reuses the same
  Ollama chat endpoint and the same one-shot-call pattern T5 already uses.
- ✅ The budget measures what is actually sent (RAG + few-shot included),
  follows `--num-ctx`, has a single default, and `num_ctx` reaches every
  chat call — the feature now protects against the real failure mode
  (silent truncation by Ollama) instead of a budget that could never be the
  binding constraint.
- ✅ The web server and the CLI share the same behavior, as ADR-0035 asks.
- ❌ `count_tokens`'s 4-chars-per-token estimate is not what qwen3's real
  tokenizer would report — it can be off by a meaningful margin, especially
  on code (denser in tokens than prose) or non-English text. It is a
  trigger heuristic, not a billing-grade measurement. `DEFAULT_NUM_CTX
  = 8192`, the 2000-token response margin, `DEFAULT_KEEP_RECENT = 6` and the
  4-chars-per-token ratio are all **estimates, not measurements**. A script
  exists — `scripts/bench_token_budget.py` compares the estimate against
  Ollama's own `prompt_eval_count` on real exchanges — but it **has not been
  run yet** (no chat-capable Ollama reachable when it was written), so there
  is still no `docs/performance/M2-*.md` with a sourced number (review: PR
  #97). Run it on the pod and report the result there before treating the
  ratio as calibrated.
- ❌ `DEFAULT_NUM_CTX = 8192` is a compromise nobody measured: a larger
  window costs GPU memory (the KV cache grows with it) and latency on every
  call, a smaller one summarizes more often. The pod's real headroom for a
  given model is not in `docs/performance/` either. A team on a small GPU may
  need to lower it with `--num-ctx` (the budget follows), and one with room
  to spare raise it.
- ❌ The summarization is wired where there is a history to summarize: the
  CLI's loop and the web server. Sub-agents, `sensai-schedule` and
  `sensai-eval` send `num_ctx` but apply no budget — each of those starts
  from a short, fresh message list (the delegated task, the scheduled
  prompt, the evaluation question), so there is no backlog to condense; what
  can grow inside their own tool loop is the next point.
- ❌ The ReAct loop's own intermediate messages (tool calls, tool results,
  sub-agent exchanges during a single turn) are never counted by this
  budget — `compress_messages()` only sees the messages built *before*
  `run_agent_turn()` starts; what happens inside that turn (e.g. several
  large `read_file` results) can still exceed `num_ctx` within a single
  turn, which this ADR does not protect against. Guarding the ReAct loop
  itself would be a materially bigger change to shared code used by every
  lot, deliberately left out of this ADR's scope; documented here instead
  of silently assumed away.
- ❌ A new summary is computed on every turn once the budget is crossed,
  with no caching: each such turn pays one extra model call before the
  real answer, and that latency repeats for as long as the conversation
  stays above the budget. (An earlier version of this ADR incorrectly
  described this as "summarizing a summary" — that never happens, since
  the summary is folded into the system message and never re-enters the
  turns that could be summarized again; the real cost is the repeated
  latency, not compounding loss of detail.) Caching the summary per
  session until new turns invalidate it would remove the repeated cost;
  not implemented here, accepted as a known cost for now.
- ❌ The summarization call has no overall time bound of its own: it is a
  single plain chat call (`stream_chat_messages`, no tools), so
  `run_agent_turn`'s `MAX_ITERATIONS` doesn't apply, and the only limit is
  the 60 s read timeout of the stream, which measures the wait for the next
  chunk, not the call as a whole. A slow model can therefore hold a turn
  for longer than 60 s.
- ❌ The summary text does not go through `filter_output` (EV2). Its input
  is the older saved turns, which already passed the input guard and the
  tool-output filters when they were produced, and the summary is neither
  shown nor saved — it only goes back to the same model, inside the system
  message. That makes it acceptable, not risk-free: a model that rephrases a
  secret it saw earlier could carry it into the summary, and nothing here
  would catch it. RAG passages and the few-shot example, the two blocks that
  do reach the model without having been through a guard earlier, are
  filtered where they are attached (`filter_output`), and they are never
  part of what gets summarized.
- ❌ The web interface has no event type for "history summarized" (adding one
  would change the event contract with the frontend, ADR-0035): it only
  surfaces failures and irreducible overflows, as notices. A user of the web
  chat never sees that a summary took place, unlike the CLI's info line.
