# ADR-0027 - EV2 input filter: deterministic rules, applied before everything else

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Meric (Workstream B); pending team review
- **Workstream**: B (`execution/guardrails.py`); A (`cli.py` calls the filter); D (the web interface will have to call it too)

## Context
[EV2] requires two interceptors: on output (mask secrets and personal
data, done) and **on input** ("detect and block unsafe or out-of-scope
prompts before they reach the model", according to configurable
rules). Only the second was missing: `filter_input` raised
`NotImplementedError`. We need to decide *how* to judge a prompt and *where*
to call the filter. Constraints: the project runs locally, with no third-party service
(ADR-0001, ADR-0004); the filter runs on every message, so it must be
fast; and it must be testable without a model.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| **Deterministic rules (regex) in French and English** | Instant, no dependency, testable line by line, explains its refusal (rule name), configurable through a simple file | Bypassable by rephrasing, another language or encoding; false positives on legitimate security questions |
| Local LLM classifier (the model judges the prompt) | Understands rephrasings | One more call per message (latency, VRAM on the 8B dev model), non-deterministic, itself manipulable by the prompt it judges, impossible to test without a model |
| Hosted moderation API (e.g. OpenAI Moderation) | Model trained for this | Sends every prompt, hence the user's code, to a third party: contradicts the "everything stays local" choice (see `docs/legal/`); extra API key and quota |

## Decision
`filter_input(text, rules) -> (allowed, text_or_reason)` applies deterministic
regex rules. They only target unambiguous verb + object pairs:
overriding instructions, revealing the system prompt, known jailbreak
personas, malware creation, credential theft.

1. **Refusal**: the message reaches neither the model, nor RAG search, nor the
   profile, nor the saved session. The reason names the rule and does not repeat
   the prompt.
2. **Pasted secrets**: an API key in the prompt is not refused but
   **masked** before the model, the session and the profile (same masking as the
   tools). Emails and card numbers typed by the user are not
   masked on input: they wrote them on purpose.
3. **Text cleaned, not normalized**: invisible characters and ANSI sequences
   removed (an instruction hidden in pasted text), but no NFKC on the
   returned text, so the user's code is not rewritten. The rules, however,
   are evaluated on the normalized text, which defeats full-width letters
   and zero-width characters.
4. **Called first in the `cli.py` loop**, before commands
   (`/remember` writes to the profile).
5. **Fail closed**: a filter that crashes blocks, like the gateway
   (ADR-0006).
6. **Configurable, but only additively**: the `input_blocklist` key in
   `config.json` adds rules (this is how "out of scope" is configured,
   e.g. a project that must not talk about salaries). Default rules
   cannot be disabled by the config, same principle as
   permission modes. An invalid rule stops startup.

## Consequences
- ✅ Obvious attacks are stopped without calling the model, with an explained
  refusal; a secret pasted into the chat no longer ends up in `sessions.db`.
- ✅ Every rule has a test; `tests/test_cli_input_filter.py` fails if
  the call is removed from `cli.py`.
- ❌ **Bypassable.** A rephrasing, another language, base64 or an
  attack spread over several messages gets through. This filter removes the obvious
  cases; it does not replace the model or the confirmation before action
  (ADR-0006), which remain the real barrier.
- ❌ **Known false positives.** A legitimate question quoting an attack
  phrase ("how do I prevent “ignore previous instructions”?") is
  refused; the message asks the user to rephrase. A course on malware too,
  unless detection/analysis is mentioned. The prompt text is not shown to
  the user in the refusal, but the rule is.
- ❌ **Partial coverage.** The filter is only wired into the CLI. Prompts
  of scheduled tasks (X5) are written by the user when creating the
  task and are not filtered; the web interface (Workstream D) will have to
  call `filter_input` as well, otherwise it bypasses the protection.
- ❌ Rules are hand-written for two languages: adding one
  takes work.
- Follow-up: add these attacks to the EV4 corpus to measure what the filter
  actually catches; **revisit this decision** if false positives hinder
  normal use, or if a measured local classifier stays under ~200 ms per
  prompt on the demo machine.
