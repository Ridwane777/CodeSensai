# Full trial of every feature - 2026-11-01, afternoon

State of `main` after PRs #115 to #117: A7 visible in the web, Python 3.12
CI, time in the prompt, ADRs accepted. Same day as the
[morning trial](trial-2026-11-01.md), on two other RunPod pods (the first one
was stopped halfway, the run went on with a second one).

## Machine and method

- **Model**: `qwen3-coder:30b` and `bge-m3` served by Ollama on RunPod pods
  (24 GB GPU), through RunPod's HTTP proxy. Pod addresses are not in the repository.
- **Client**: Linux workstation, Python 3.12, Docker for the sandbox, headless
  Chromium (Playwright) for the interface.
- **Project**: a fresh throwaway folder (`stats.py` whose `moyenne` crashes on an
  empty list, `notes.md`, two few-shot examples with `fewshot_min_score` 0.6, then
  two personas in `config.json`); fresh data folder, `~/.sensai` not touched.
- **Four passes**: the features added since the morning trial (API); one
  scenario per older feature (API); one long conversation mixing features, then
  the terminal and `sensai-schedule`; the interface in the browser.
- One measurement per scenario: orders of magnitude, not benchmarks.

## Results

| Pass | Result |
| --- | --- |
| New features (A7 route and `fewshot` event, A5 persona per conversation, A4 prompt trial, EV3 log, EV4 re-run from the server, `schedule_task` tool, date and time, RAG sources) | ✅ all. A5 needed two personas in `config.json` (a fresh project has only the default one); the `math-tutor` persona never called its disabled `run_code`. The time given was the start of the conversation, "13:45 (UTC+0100)", without `web_search` |
| One scenario per older feature (X4, write diff, M4, A2 delegation and team, regenerate, A6 cache, attachment, EV1, X3, #44, X2, X5, export, delete) | ✅ 15 of 16; the language preference failed (finding 1) |
| Global run (11 steps: sandbox, secret masked, injection blocked, M2 summary, terminal resume, task run by `sensai-schedule`) | ✅ all |
| Browser (login, sidebar, Markdown, token bar, regenerate, form, diff, artefact, EV1, planning, share link, memory, reopen, phone width, EV4 page, log, A7 mention and card, A5 selector, A4 button) | ✅ all, after fixing the test script (see below) |

Failures caused by the test scripts, not the product: the EV3 scenario required a
`read_file` call although the RAG passage already held the answer (the log
recorded the turn correctly); four browser steps used wrong selectors (an input
with no `type`, an ambiguous "Add" button, a hidden "Real agent" label on a
phone, a new tab not logged in). They passed once the scripts were fixed. The
first browser form attempt also hit the cold start of the second pod (model
loading and project indexing took more than 2 minutes).

## Findings

1. **The language preference was ignored (fixed).** With "Always
   answer in English" (written in French) in the profile, answers stayed in French, with or without
   a few-shot example. The real system prompt showed why: the profile came in the
   middle, followed by the French state document and facts block.
2. **Tools called for a simple question (fixed).** "Where is the function
   moyenne? One sentence." (asked in French) gave `read_file`, `recall_facts` and four `run_code`;
   another question gave `update_state` and `save_fact`. The facts block said
   "before answering about one of them, consult it with recall_facts", and the
   state block invited `update_state` "at the end of a task", which the model read
   as every question.
3. **Repeated answer (fixed in the saved answer).** The text written before a tool call is
   followed by a rephrased version after it ("…located in `stats.py`, starting at
   line 4.The function `moyenne` is defined in…"). The fix of the morning trial
   only removes a segment repeated word for word.
4. **Persona id shown while thinking (fixed, cosmetic).** The header of a
   pending answer says "assistant" (the id) before "CodeSensai" (the name).
5. **The CLI rebuilt the time at every turn (fixed).** A comment written in #117
   said the CLI built its prompt once; it rebuilds it every turn, so the time
   changed and Ollama had to re-read the whole conversation.

## Fixes and re-check (same day, same pod)

Branch `fix/preferences-and-tool-eagerness`:

- the profile comes **last** in the system prompt, under "User profile
  (takes priority)", and says it comes before the language of the question, the
  examples and the documents (`build_system_prompt(..., extra=...)`, CLI and web);
- when a few-shot example is attached, the preferences are **repeated next to it**,
  and the example block says not to copy its answer;
- the facts block asks for `recall_facts` only when the answer is neither in the
  conversation nor in the passages, and `save_fact` only for facts learnt in the
  conversation; the state block asks for `update_state` only after changing the
  project or when asked;
- the CLI keeps the time of the start of the session, like the web.

| Question, asked in French (preference "answer in English") | Before | After |
| --- | --- | --- |
| "Quelle commande lance les tests ? Une phrase." (example attached) | French, copied from the example | English, one `recall_facts` |
| "Comment lancer les tests du projet ?" (same question as the example) | French | **still French** |
| "Quel style de tests utiliser ?" (example attached) | French, `recall_facts` ×2, `save_fact`, `update_state` | English, no tool |
| "Où se trouve la fonction moyenne ? Une phrase." (no example) | French, `read_file`, `recall_facts`, `run_code` ×4 | English, one `read_file` |
| Same question, no preference | French | French |

One try per question: the behaviour still depends on the model. When the question
was the example's question word for word, the example still won.

## Second round of fixes (same day, same pod)

- **Identical question**: when the user has preferences and the question is the
  example's question (case, punctuation and spaces aside), the example is not
  attached (`fewshot.worth_attaching`). Without preferences it still is: copying
  a good answer is then what A7 is for.
- **Rephrased answer**: `AnswerBuilder` also drops a segment when at least 80 % of
  its words come back in a later segment. A short announcement before a tool call
  ("I'll read stats.py…") stays. This applies to the saved answer (reload,
  export, cache, terminal history); the live stream still shows both segments as
  they arrive.
- **Persona name**: the interface remembers the names sent by the server
  (`rememberPersonaNames`), so a pending answer is headed "CodeSensai", not "assistant".

| Re-check, questions asked in French (preference "answer in English") | Result |
| --- | --- |
| "Comment lancer les tests du projet ?" (the example's question) | ✅ English, example not attached, no tool |
| "Quelle commande lance les tests ? Une phrase." (example attached) | ✅ English, no tool |
| "Où se trouve la fonction moyenne ? Une phrase." | ✅ English, no tool, saved answer said once |
| "Comment lancer les tests du projet ?" without preference | ✅ example attached, French answer |
| Browser: header of an answer while thinking, then done | ✅ "Answer from CodeSensai" both times |
