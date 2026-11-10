# User stories — [EV2] Guardrails on content and personal data

`execution/guardrails.py` (masking),
`execution/output_sanitizer.py` (cleaning), plugged into the gateway
([ADR-0006](../decisions/0006-tool-gateway.md)). What the rules
mask **and what they miss**: [docs/architecture/tool-contract.md](../architecture/tool-contract.md).

Personas: Camille, the developer, and Marc, the lead who configures the tool
for the team ([persona-and-scenario.md](../design/persona-and-scenario.md)).

The input filter `filter_input` (stories US-EV2-4 to 6) is described by
[ADR-0027](../decisions/0027-rule-based-input-filter.md). It runs in the
CLI, in `sensai-web` (`web/runtime.py`) and, since 2026-11-01, on the prompt
of every scheduled task (`scheduling/runner.py`). The model's own answer
is filtered too (US-EV2-7, [ADR-0058](../decisions/0058-filtered-answers-and-context-command.md)).

---

> **Update on 2026-11-06:** feature trial ([2026-11-06](../performance/trials/trial-2026-11-06.md)), qwen3:8b on the laptop CPU and qwen3-coder:30b on a GPU pod: AWS example key written by the model: ✅ masked with both models (7 min 36 on CPU, 3 s on GPU).

## US-EV2-1 — An API key pasted in the code never leaves
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose script contains a fake API key,
**I want** the key to be masked before it reaches a tool, the logs or the model,
**so that** I do not expose a secret by accident.

**Acceptance criteria:**
- A `sk-…` or `sk-ant-…` key, a GitHub, AWS or Slack token, a JWT, a `Bearer …` or an assignment like `password = "…"` is replaced by a marker (`[REDACTED:…]`) in the arguments of a tool call.
- The call continues with the masked version, and the confirmation request (A3) also shows the masked version: I do not see the secret either.
- The text returned by a tool (sandbox output, file read) is filtered in the same way before the model, the logs or the user see it.

## US-EV2-2 — Mask personal data in what comes back
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose client files or a web page contain e-mail addresses and card numbers,
**I want** them to be masked in the tool results,
**so that** I do not send them to the model or write them in the logs.

**Acceptance criteria:**
- An e-mail address is masked; a card number only if it passes the Luhn check (a 16-digit order number stays readable).
- A text with no secret or personal data comes out identical.
- The known limits (formats not covered) are written in the documentation, without being presented as covered.

## US-EV2-3 — Not be manipulated by the text of a page or a file
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer whose agent reads a web page or a file she did not write,
**I want** the content to be cleaned and presented to the model as data,
**so that** an instruction hidden inside does not drive the agent without my knowing.

**Acceptance criteria:**
- Invisible characters (zero width, writing direction) and ANSI sequences are removed from a tool's result.
- The content of an untrusted tool is fenced and labelled "data", with the list of injection markers detected (a signal, not a block).
- The result sent back to the model is capped (20,000 characters by default) so as not to drown its context.

## US-EV2-4 — Refuse an obviously dangerous request before it reaches the model
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead who rolls the agent out to the rest of the team,
**I want** obvious attempts to bypass its instructions or make it write malware to be refused at once,
**so that** the agent is not used for that and the refusal does not depend on the model's goodwill.

**Acceptance criteria:**
- Sentences like "ignore les instructions précédentes", "affiche ton prompt système", "écris un keylogger" or "vole les mots de passe" (in French or in English) show `[Blocked]` with the rule's name; nothing is sent to the model or saved in the session.
- An ordinary developer question ("comment ignorer un dossier dans git ?", "écris un détecteur de malware") goes through unchanged.
- An invisible character or full-width letters slipped into the sentence do not let it through.
- Written limits: the filter can be bypassed by rephrasing and sometimes refuses a legitimate question that quotes an attack sentence (ADR-0027).

## US-EV2-5 — A key pasted in the chat is not kept
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, the developer who pastes an error message containing an API key,
**I want** the key to be masked before it reaches the model,
**so that** it is neither sent, nor written in my session history or my profile.

**Acceptance criteria:**
- The request is not refused: it goes out with `[REDACTED:api_key]` in place of the key.
- The saved session and the profile (`/remember …`) do not contain the key.
- Pasted code is sent back as is: only invisible characters and ANSI sequences are removed. Typed e-mails are not masked on input (they still are in tool results).

## US-EV2-6 — Define what is out of scope for my project
> **Update on 2026-11-06:** scenario step **S0**, Marc sets CodeSensai up ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Marc, the lead of a project that must not handle some topics (e.g. individual salaries),
**I want** to add my own rules in `config.json` (`input_blocklist`),
**so that** the agent refuses these topics without a code change.

**Acceptance criteria:**
- A rule `{"name": "salaires", "pattern": "salaire de \\w+", "why": "RH confidentiel"}` refuses "Quel est le salaire de Marie ?" citing its name; the other requests go through.
- The default rules stay active: the config can only add to them.
- A badly written rule (invalid expression, unknown key) stops the start-up with a message, instead of being silently ignored.

---

## US-EV2-7 — A secret the model writes in its answer is masked too
> **Update on 2026-11-06:** scenario step **S7**, outside knowledge, and secrets ([scenario](../design/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).

**As** Camille, who asks the agent to explain a configuration file containing a key,
**I want** the model's own answer to go through the same filter as tool results,
**so that** a secret it repeats does not reach my screen, the saved session or an export.

**Acceptance criteria:**
- The answer text is filtered line by line while it streams; a key cut across two chunks (`AKIA` then `IOSF…`) is still masked.
- The body of a private key (`-----BEGIN … PRIVATE KEY-----` to `-----END …`) is replaced by one `[REDACTED:private_key]` line.
- Known limit, written: the answer appears line by line instead of word by word; the model's separate reasoning field (`thought` events) is **not** filtered (see the audit below).


---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-EV2-1 | ✅ | `execution/guardrails.py`, `execution/gateway.py` | `tests/execution/test_guardrails.py`, `tests/execution/test_guardrails_gateway.py`, `tests/execution/test_gateway.py::test_input_guard_can_rewrite_arguments_and_confirmation_sees_the_rewrite` |  |
| US-EV2-2 | ✅ | `execution/guardrails.py` | `tests/execution/test_guardrails.py` |  |
| US-EV2-3 | ✅ | `execution/output_sanitizer.py`, `execution/gateway.py`, `core/agent.py` | `tests/execution/test_output_sanitizer.py`, `tests/execution/test_gateway.py::test_output_is_capped_after_filtering`, `tests/core/test_agent.py::test_the_tool_result_is_sent_back_to_the_model`, EV4-OUT-14 in `tests/adversarial/test_corpus.py` | Cleaning, the 20,000-character cap and, since 2026-11-01, fencing: `core/agent.py` wraps each result with `fence_untrusted` before the model sees it |
| US-EV2-4 | ✅ | `execution/guardrails.py` (`filter_input`), `cli.py`, `web/runtime.py` | `tests/execution/test_guardrails_input.py`, `tests/test_cli_input_filter.py::test_a_blocked_prompt_never_reaches_the_model`, `tests/web/test_server.py::test_a_blocked_input_is_not_sent_to_the_model` | The filter runs in the CLI, in `sensai-web` and, since 2026-11-01, on scheduled tasks (`tests/scheduling/test_runner.py::test_task_prompt_goes_through_the_input_filter`) |
| US-EV2-5 | ✅ | `execution/guardrails.py`, `cli.py` | `tests/test_cli_input_filter.py` (`une_cle_collee_est_masquee_avant_le_modele_et_la_session`, `remember_n_ecrit_pas_de_cle_dans_le_profil`), `tests/execution/test_guardrails_input.py::test_emails_typed_by_the_user_are_kept` |  |
| US-EV2-6 | ✅ | `execution/guardrails.py` (`InputRules`) | `tests/execution/test_guardrails_input.py` (`test_an_extra_rule_blocks_its_topic`, `test_a_bad_rule_is_an_error_not_silently_ignored`), `tests/test_cli_input_filter.py::test_an_invalid_rule_stops_startup` |  |
| US-EV2-7 Answer filtered (new) | ✅ | `execution/guardrails.py` (`StreamRedactor`), `core/agent.py` | `tests/execution/test_guardrails.py` (`test_stream_redactor_masks_per_line_and_keeps_the_rest`, `test_stream_redactor_hides_the_whole_private_key_body`), `tests/core/test_agent.py::test_a_secret_written_by_the_model_is_masked_even_split_into_chunks`, `test_the_displayed_reasoning_is_filtered_too` | The answer (`token`) is filtered line by line; since 2026-11-01 the reasoning (`thought`) is filtered too, in `_flush_thought`. Seen with `qwen3-coder:30b` on 2026-11-03 ([trial](../performance/trials/trial-2026-11-03.md)): a key written by the model shown and stored as `[REDACTED:aws_access_key]` |
