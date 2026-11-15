# ADR-0058 - The model's answer is filtered while it streams; /context shows what is sent

- **Status**: Accepted (2026-11-02, decided by Ridwane, Workstream C)
- **Date**: 2026-11-01
- **Deciders**: Ridwane (Workstream C)
- **Workstream**: All (EV2 is Workstream B's, the display is Workstream D's)

## Context

EV2 was incomplete: the user's message filter was not implemented and the
model's answer was not filtered (only the tools were protected). The input filter was added since
(ADR-0027); the answer was still shown, saved and cached as the model wrote it,
so a secret the model repeated from its memory or from a passage reached the
screen, the session and the export.

*Context Engineering* (2/4): "no command shows the exact prompt sent".

The answer streams in small pieces: a key can arrive cut in two ("AKIA", then
"IOSF…"), so filtering each piece alone would miss it.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Filter only the saved answer | streaming unchanged | the secret is still on screen and in the web stream |
| Filter each piece as it comes | streaming unchanged | misses a secret cut between two pieces |
| Buffer the whole answer, filter, then show it | simplest, nothing missed | no streaming at all, which the subject requires |
| **Buffer to the end of each line, filter the line, emit it** | nothing missed: no pattern of `filter_output` spans two lines, except a private key, followed apart | the text appears line by line instead of word by word |

## Decision

- `StreamRedactor` (`execution/guardrails.py`) applies `filter_output` to each
  complete line of the answer in `run_agent_turn`, so the CLI, the web server,
  the scheduler and the sub-agents get the same filter. The body of a private
  key is removed whole. The model keeps its own unfiltered text in its working
  messages (it wrote it).
- A `Token` is still emitted for every piece received, empty until the line is
  complete, so a turn stays interruptible (Escape, "Stop") between pieces.
- `/context`, in the terminal and in the web chat, shows the messages that
  would be sent now (system prompt with persona, profile, state document and
  facts; history), each with its estimated tokens, plus `num_ctx`, the budget
  and the generation settings (ADR-0057). The next question's RAG passages and
  few-shot example are not there yet: they are attached when it is sent, and
  the command says so.

## Consequences

- ✅ No credential or personal data matched by `filter_output` reaches the
  screen, the saved session, the cache or an export, from the tools or from
  the model.
- ✅ The prompt actually sent can be shown during the demo, with its size.
- ❌ The answer appears line by line: a long paragraph shows up in one go.
- ❌ The filter only knows the patterns of `filter_output`; an obfuscated
  secret (base64, zero-width spaces) still passes, as listed in the EV4 gaps.
- ❌ `/context` prints the whole system prompt, which is long (state document,
  facts): readable in the terminal, heavy in the web chat.
- Follow-up: `tests/core/test_agent.py`
  (`test_a_secret_written_by_the_model_is_masked_even_split_into_chunks`),
  `tests/execution/test_guardrails.py`, `tests/web/test_server.py`
  (`test_context_shows_the_exact_prompt_without_calling_the_model`).
