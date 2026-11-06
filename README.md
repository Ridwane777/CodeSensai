# Sensai — CodeSensei

A local developer agent: it reads your codebase (RAG), reasons step by step
(ReAct), runs and fixes code in a sandbox, reads and writes project files,
searches the web, asks for confirmation before any risky action, masks
secrets, keeps track of your sessions, maintains a project state document,
remembers important facts and can work on its own at regular intervals —
connected to a model served by Ollama, without an LLM framework.

See [docs/architecture/architecture.md](docs/architecture/architecture.md) for
the components, [docs/decisions/](docs/decisions/README.md) for the reasons
behind the technical choices, and [docs/README.md](docs/README.md) for the map
of the project file.

**Before your first commit: [CONTRIBUTING.md](CONTRIBUTING.md)** — branches,
reviews, what must pass before a PR.

## Installation

Requirements: Python 3.12 or later, [Ollama](https://ollama.com), and Docker
to run code and search the web (without Docker, these two tools return a
clear error; everything else works).

```bash
ollama pull qwen3:8b
ollama pull bge-m3      # embeddings pour la recherche dans le projet (R1), ~1,2 Go
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                 # ou, versions exactes : pip install -r requirements-dev.txt && pip install -e . --no-deps
docker pull python:3.12-slim            # sandbox d'exécution (T2)
docker build -t sensai-browser:latest docker/browser   # navigateur de recherche (T3), ~1,1 Go, ~12 min
```

`requirements.txt` pins the tested versions of the runtime dependencies,
`requirements-dev.txt` adds pytest and ruff. Licences and replacements:
[docs/dependances.md](docs/dependances.md).

## Running

```bash
sensai
# modèle de dev par défaut : qwen3:8b (voir docs/decisions/0004-modele-et-infrastructure.md)

# qwen3:8b en local, explicitement (Ollama sur cette machine) :
ollama serve &                          # si Ollama ne tourne pas déjà
sensai --host http://localhost:11434 --model qwen3:8b
sensai-web --host http://localhost:11434 --model qwen3:8b   # interface web
# sur un portable sans GPU : 7 à 11 min par question, prévoir "request_timeout": 1800
# (docs/guide/lancer-et-utiliser.md) ; team_task (A2) et /structured (T5) échouent
# avec ce modèle (docs/performance/essais/essai-2026-11-06.md)

# validation sur le gros modèle, servi par un pod RunPod (proxy HTTP du pod) :
sensai --host https://<id-du-pod>-11434.proxy.runpod.net --model qwen3-coder:30b
```

The host does not have to be `localhost`: `--host` is enough to point to a
remote Ollama instance. The code does not change, only the configuration.

## Features

### [A1] The agent reasons and acts with tools

For each question, the agent (a ReAct loop on Ollama's native tool calling)
chooses to call a tool, reads the result, and starts again until it answers,
with at most 6 model calls per turn by default (`max_iterations` in
`config.json`, 1 to 50, [ADR-0057](docs/decisions/0057-generation-parameters-and-loop-limit.md)). Each step is shown:

```
Vous > Lis calcul.py, exécute-le, corrige le bug, puis vérifie.
  → read_file({'path': 'calcul.py'})
  ✓ read_file : def moyenne(valeurs): ...
  → run_code({'code': '...'})
[Confirmation] L'agent veut utiliser l'outil « run_code » (risque : execute) [y/N] o
  ✗ run_code : Execution failed: NameError: name 'valeur' is not defined ...
  → write_file({'path': 'calcul.py', ...})          (confirmation, diff affiché)
  → run_code({'code': '...'})
  ✓ run_code : 4.0
```

| Tool | Feature | Risk | What it does |
|---|---|---|---|
| `search_codebase` | R1 | read | Searches the project's code and docs |
| `update_state` | M4 | write | Updates one section of `SENSAI.md` (see M4) |
| `save_fact` | M3 | write | Saves a fact about the project (see M3) |
| `recall_facts` | M3 | read | Finds saved facts |
| `read_file` | T4 | read | Reads a file from the current folder (1 MB at most) |
| `write_file` | T4 | write | Creates or replaces a file, showing the diff; never overwrites silently |
| `run_code` | T2 | execute | Runs Python in a disposable Docker container: no network, read-only system, unprivileged user, 256 MB, ½ CPU, 10 s by default (60 s at most) |
| `web_search` | T3 | network | Searches the web from a Chromium isolated in Docker (DuckDuckGo first, Bing as a fallback, [ADR-0040](docs/decisions/0040-recherche-web-duckduckgo-et-repli-bing.md)) |

Other tools are listed in "Other delivered features" below (`ask_user`,
`delegate_task`, `team_task`, MCP tools).

Every call goes through a **gateway** (ADR-0006) that:
- **asks for confirmation** before any write or execution [A3]; without an
  explicit "yes" (empty answer, Ctrl+C, end of input), it is a refusal;
- **masks secrets** [EV2] in tool arguments and results: API keys (`sk-…`,
  AWS, GitHub, Slack), private keys, JWT and Bearer tokens, passwords written
  as `name = value`, e-mails and valid card numbers become `[REDACTED:…]`;
  the **model's own answer** goes through the same filter while it streams,
  line by line (ADR-0058), so a secret it repeats never reaches the screen,
  the saved session or an export; its separate reasoning text (`thought`) is
  filtered as well;
- **refuses** files outside the current folder and sensitive files (`.git`,
  `.env*`, `.ssh`, `*.pem`, `*.key`, `id_rsa*`, `credentials*`,
  `secrets*`…), stops a tool after 120 s and strips invisible characters
  from its output.

Settings live in `config.json` (an unknown key stops the CLI with a message
instead of being ignored):

```json
{
  "tools": {"disabled": ["web_search"], "tool_timeout_s": 60},
  "files": {"read": ["src", "docs"], "write": ["src"]}
}
```

`tools`: removed tools, modes (`allow`, `ask`, `deny`), timeouts (details in
the [tool contract](docs/architecture/tool-contract.md)); a setting can never
remove the confirmation for writing and running. `files`: readable and
writable folders, relative to the current folder ([ADR-0011](docs/decisions/0011-permissions-fichiers.md)).
Every tool result reaches the model wrapped in
`<tool_output trust="untrusted">` (gap EV4-OUT-14, fixed on 2026-11-01): the
system prompt says such content may hold instructions that must not be
followed. Choices:
[ADR-0003](docs/decisions/0003-tool-calling-natif-ollama.md),
[ADR-0006](docs/decisions/0006-passerelle-d-outils.md),
[ADR-0011](docs/decisions/0011-permissions-fichiers.md),
[ADR-0012](docs/decisions/0012-sandbox-docker-chromium.md),
[ADR-0014](docs/decisions/0014-moteur-de-recherche-bing.md),
[ADR-0017](docs/decisions/0017-user-agent-du-navigateur-de-recherche.md);
sandbox details: [docs/architecture/sandbox.md](docs/architecture/sandbox.md); tool
contract: [docs/architecture/tool-contract.md](docs/architecture/tool-contract.md); real run:
[docs/performance/essais/essai-2026-10-14.md](docs/performance/essais/essai-2026-10-14.md).

### [M1] Memory between sessions, and profile

CodeSensei resumes the last conversation of the project it is started from,
and knows your preferences without you repeating them.

```bash
sensai                      # reprend la dernière session de ce projet
sensai --new-session        # repart d'une conversation vierge
sensai --session 598e74dbd321   # reprend une session précise
sensai --retention-days 90  # garde les sessions 90 jours (défaut : 30, 0 = toujours)
```

At startup, sessions with no message for more than 30 days are deleted, and
the CLI says so.

In the chat:

| Command | Effect |
|---|---|
| `/remember <text>` | Adds a preference to the profile ("use pytest") |
| `/profile` | Shows the profile |
| `/forget` | Clears the preferences |
| `/sessions` | Lists this project's sessions |
| `/schedule …` | The `sensai-schedule` commands without leaving the chat (X5): `/schedule list`, `/schedule add …` |
| `/eval …` | The `sensai-eval` commands (EV1): `/eval run --dataset … --out …`, `/eval compare …` |

```
$ sensai
Session 598e74dbd321 reprise (2 messages). --new-session pour repartir.
Vous > /remember réponds en français et utilise pytest
Préférence enregistrée : réponds en français et utilise pytest
```

The data stays on your machine, outside the repo: `~/.sensai/sessions.db`
(history) and `~/.sensai/profile.json` (profile, editable by hand). The
folder can be changed with `--data-dir`, the `SENSAI_HOME` variable or the
`data_dir` key in `config.json`. Choice and trade-offs:
[ADR-0007](docs/decisions/0007-persistance-des-sessions.md); use cases:
[M1 user stories](docs/user-stories/M1-session-persistence.md); personal
data: [docs/legal/donnees-locales.md](docs/legal/donnees-locales.md).

### [R1] Search in the project's code and documentation

On the first question of the session, CodeSensei indexes the folder it is
started from, then adds the relevant passages of the project, with their
source, to each question. Next times, only changed files are re-indexed.

```
$ sensai
Vous > Où vérifie-t-on qu'une session inconnue ne fait pas planter le CLI ?
Indexation du projet pour la recherche (bge-m3)...
Index du projet à jour : 391 passages (66 fichier(s) indexé(s), 0 retiré(s)).
CodeSensei > ... dans src/sensai/cli.py, lignes 112-116, une clause except KeyError ...
```

```bash
sensai --no-rag              # sans recherche dans le projet
sensai --rag-top-k 3         # 3 passages par question au lieu de 5
sensai --rag-min-score 0.6   # seuil de pertinence (défaut 0,54)
sensai --no-rag-rerank       # sans reclassement par le modèle (~3 s de moins)
```

During the conversation, the agent can also search the project itself with
the `search_codebase` tool, several times and in its own words, without
asking for confirmation (read only). It is not offered with `--no-rag`.

**[R2] Advanced search.** Each search combines two rankings: by meaning
(embeddings) and by exact words (BM25, useful for code names such as
`FactStore`), merged by rank (RRF). The chat model then reranks the top 10
passages. Measured on this repo: the right file comes first 11 times out of
15 instead of 5, and questions with no answer get no passage.
`search_codebase` also accepts `kind` (`code` or `doc`) and `path` (a
folder). Choice and measurements:
[ADR-0032](docs/decisions/0032-rag-hybride-et-reclassement.md),
[R2 measurements](docs/performance/R2-rag.md),
[R2 user stories](docs/user-stories/R2-advanced-rag.md).

Never indexed: `.env*`, keys (`*.pem`, `id_rsa*`…), binaries, files over
1 MB, and everything excluded by `.gitignore`.

**Documents (issue #64).** The project's PDF, Word, PowerPoint, Excel, EPUB
and Outlook files are converted to text in an isolated container, then
indexed: "which frameworks are required?" finds the answer in `sujet.pdf`
without naming it. The agent can also read them in full with `read_file`.
For any other format, it gets the file type and what to do, never made-up
content. The image must be built once:
`docker build -t sensai-docs:latest docker/docs` (659 MB). Without it, the
documents are listed with what to do. Choice and measurements:
[ADR-0034](docs/decisions/0034-lire-tous-les-formats-de-fichier.md),
[runs](docs/performance/64-documents.md). The index is stored in the data
folder (`~/.sensai/rag.db`). Choices and measurements:
[ADR-0009](docs/decisions/0009-rag-sur-la-codebase.md),
[ADR-0013](docs/decisions/0013-branchement-de-l-outil-rag.md),
[measurements](docs/performance/R1-rag.md),
[R1 user stories](docs/user-stories/R1-basic-rag.md).

### [A4] Prompt versions (team tool)

The agent's prompts are stored as immutable versions in `prompts/`
(`system/v1.txt`, `memory/v1.txt`…); the index `prompts/versions.json` gives
the version in use for each prompt. At launch, `sensai` shows the versions
used (`prompts : system v1, memory v1`).

```bash
sensai-prompt history system                          # versions : n°, date, auteur, description
sensai-prompt show system > brouillon.txt             # partir du texte en service
sensai --system-prompt brouillon.txt                  # essayer le brouillon
sensai-prompt save system brouillon.txt "précise X"   # le ranger : nouvelle version
sensai-prompt diff system v1 v2                       # comparer
sensai-prompt use system v2                           # la mettre en service
sensai-prompt use system v1                           # revenir en arrière
sensai-prompt check                                   # cohérence du registre (aussi vérifiée en CI)
```

A version file is never edited: to fix a prompt, you save a new version.
`use` changes `prompts/versions.json`: commit it to apply it to the whole
team. Choice:
[ADR-0010](docs/decisions/0010-versionnement-des-prompts.md),
[real run](docs/performance/A4-prompts.md),
[A4 user stories](docs/user-stories/A4-prompt-versioning.md).

### [X1] Web interface

**`sensai-web`** serves the interface and the API of the real agent: the same
agent as the CLI (tools, RAG, cache, memory, `SENSAI.md`, guardrails), and
the same sessions. Choice: [ADR-0035](docs/decisions/0035-serveur-web-reel.md);
real run: [docs/performance/web-reel.md](docs/performance/web-reel.md).

```bash
(cd frontend && npm ci && npm run build)   # une fois
cd mon-projet
sensai-web --host <Ollama> --model qwen3-coder:30b   # http://127.0.0.1:8000
```

The server prints an **access token** at startup: paste it into the
interface. It listens on the local machine only (`--bind` to change that,
with a warning). The CLI options (`--no-rag`, `--no-cache`…) apply. Sessions
that are too old are purged at startup.

With the server, the interface also offers:
- **questions by form** (X4): the agent can ask you a short form with the
  `ask_user` tool (text, choice, toggle; 8 fields at most, 100 s to answer)
  ([ADR-0046](docs/decisions/0046-ask-user-tool.md));
- **agent relays** (A2): a chip shows when a sub-agent (`delegate_task`) or a
  `team_task` role (explorer → developer → reviewer) takes over; MCP tools
  get an "MCP" badge ([ADR-0047](docs/decisions/0047-real-agent-handoffs-in-the-web.md));
- **share links** (X3): a read-only snapshot of the conversation, secrets
  masked, served by `sensai-web` without a token, valid 7 days, revocable
  with the "Révoquer le lien" button ([ADR-0048](docs/decisions/0048-share-links.md));
  **off by default** since [ADR-0056](docs/decisions/0056-scope-review-features-to-drop-or-limit.md):
  `"share_links": true` in `config.json` turns them on;
  the Export page can also download the **server export** (secrets masked);
- **reopening a past conversation** from the Memory page or the chat
  sidebar, which also creates and deletes conversations;
- **Markdown answers** (hand-written renderer, never raw HTML, code blocks
  with a "Copier" button) ([ADR-0049](docs/decisions/0049-hand-written-markdown-rendering.md)),
  **"↻ Régénérer"** (asks the model again, skipping the cache), Escape to
  stop an answer, **text file attachments** (3 per message, no PDF/docx),
  and the **coloured diff** of `write_file` in the confirmation card;
- since 2026-10-29 (branch `lot-d/web-real-features`,
  [ADR-0050](docs/decisions/0050-real-web-features-on-demand-evaluation.md)):
  the **token bar** with context % and the compression notice (M2, token
  counts are estimates), the **Artefact panel** filled from `SENSAI.md` and
  updated live (M4), the **sub-agents' steps** shown as "role › tool" (A2),
  **few-shot examples** as in the CLI (A7), **"Évaluer la dernière réponse"**
  on the Quality page (EV1, one model call, on demand only), and the
  **Planning page** that lists, adds, pauses and removes real `sensai-schedule`
  tasks (they run only while `sensai-schedule loop` runs);
- a **left sidebar** like claude.ai with the conversations and every tab
  (Accueil, Chat, Mémoire, Agents, Qualité, Prompts, Journal, Planification,
  Export), a drawer on small screens;
- since 2026-10-31 (branch `lot-d/interface-fluidite`,
  [ADR-0051](docs/decisions/0051-calm-chat-layout-and-motion.md)): a **calmer
  chat** — input ready on the welcome screen, a wider conversation, the
  Artefact / Sources panel folded by default, smooth animations instead of
  stop-motion ones, and a **"working" indicator** (rotating star, what the
  agent does, seconds elapsed) with the reasoning folding itself at the end.

These additions (merged on 2026-10-29) are covered by automated tests
(pytest with a scripted model, vitest) and, for reopening and the chat
display, by a headless browser run against `sensai-web` **without a model**.
They were tried with `qwen3-coder:30b` on 2026-11-01 ([trial](docs/performance/essais/essai-2026-11-01.md)); open
findings are under "Known limits". User stories:
[X1 chat comfort](docs/user-stories/X1-web-interface.md),
[X4](docs/user-stories/X4-questions-forms.md),
[X3](docs/user-stories/X3-export-publication.md).

Without a reachable server, the interface stays in **demo mode**: the engine
is simulated in the browser and the "Moteur simulé" badge says so. What is real
or simulated with the server, feature by feature:
[docs/architecture/web/simule-vs-reel.md](docs/architecture/web/simule-vs-reel.md).

In development, `npm run dev` relays `/api` and `/share` to `sensai-web`
(`http://127.0.0.1:8000`, or the address in `SENSAI_API`): start `sensai-web`
first, then paste its token, and the dev interface talks to the real agent
instead of falling back to the demo.

```bash
sensai-web --model qwen3-coder:30b   # terminal 1 : affiche le jeton
cd frontend
npm ci
npm run dev        # http://localhost:5173, relayé vers sensai-web
npm test           # tests de l'interface et du moteur simulé
npm run build
```

Node 22 minimum (required by jsdom 30 and jest-dom 7). The contract between
the interface and the engine is in `frontend/src/contract/`; `HttpEngine`
talks to the server, `MockEngine` plays the demo, and
`frontend/src/engine/wire.ts` translates the server stream for the
interface. User stories:
[docs/user-stories/README.md](docs/user-stories/README.md).

### [EV1] Evaluation of answers and hallucinations (team tool)

A "judge" model rates the relevance and coherence of answers (1 to 5) and
checks each claim against reference passages (supported, contradicted or
unverifiable, with the cited source). These are a model's **estimates**, not
measurements. The judge's prompt is a version in the A4 registry
(`prompts/judge/`).

```bash
sensai-eval run --dataset datasets/eval/ev1_sample.jsonl --out rapport.json
sensai-eval compare rapport_a.json rapport_b.json --strict   # signale un juge ou des données différents
```

In the chat: `/eval run --dataset … --out …` (the session's model is the
judge; [ADR-0028](docs/decisions/0028-commandes-schedule-et-eval-dans-le-chat.md)).

Choice: [ADR-0019](docs/decisions/0019-evaluation-par-juge-llm.md),
[method and limits](docs/performance/EV1-evaluation.md),
[EV1 user stories](docs/user-stories/EV1-evaluation-hallucinations.md).

### [M4] Project state document

The agent maintains `SENSAI.md`, at the root of the project: what is done,
what is in progress, decisions and known problems. It knows it from the first
message (even in a new session) and changes it **one section at a time**
with the `update_state` tool, after confirmation, showing the section before
and after. Other sections, and what you wrote there by hand, never change.

```
Vous > Corrige le bug de calcul.py, puis note-le dans le document d'état.
  → update_state({'section': 'Fait', 'action': 'append', 'content': '- Correction du bug…'})
[Confirmation] … SENSAI.md, section « Fait » (append) :
+- Correction du bug dans calcul.py [y/N] o
```

| Command | Effect |
|---|---|
| `/state` | Shows the document |
| `/state history` | Last changes (date, section, summary) |
| `/state undo <section>` | Undoes the last change to the section; a second time, the one before (like Ctrl+Z). Refused if the section was edited by hand in between |

Only existing sections can be changed: the four basic ones are created on
the first update, others are added by hand. `SENSAI.md` is not indexed by
the search (it is already given in full to the agent). Choice:
[ADR-0029](docs/decisions/0029-document-d-etat-du-projet.md); real run:
[docs/performance/M4-state.md](docs/performance/M4-state.md); user stories:
[M4](docs/user-stories/M4-state-document.md).

### [M3] Fact memory

The agent remembers the project's lasting facts on its own, as "entity,
attribute, value" records (`auth`, `version_redis`, `8`), and finds them weeks
later, in any session of the project.

```
Vous > On est passés à Redis 8 pour le service auth.
  → recall_facts({'entity': 'service auth'})
  → save_fact({'entity': 'service auth', 'attribute': 'utilise', 'value': 'Redis 8'})
[Confirmation] … Modifier le fait : service auth — utilise : Redis 7 → Redis 8 [y/N] o

(nouvelle session)
Vous > Quelle version de Redis utilise le service auth ?
  → recall_facts({'entity': 'service auth'})
CodeSensei > Le service auth utilise Redis 8.
```

A fact is saved only after confirmation (the confirmation also shows what is
already known about the entity, to spot a duplicate); the agent cannot
delete. `recall_facts` finds everything about an entity, or what points to a
value ("what depends on Redis?").

| Command | Effect |
|---|---|
| `/facts` | Known entities |
| `/facts <entity>` | Its facts |
| `/facts forget <entity> [attribute] [value]` | Deletes (confirmation for a whole entity) |
| `/facts history <entity>` | Creations, changes and deletions |

Facts are in `~/.sensai/memory.db`, one memory per project, with no automatic
purge. Choice: [ADR-0030](docs/decisions/0030-memoire-structuree-de-faits.md);
real run: [docs/performance/M3-facts.md](docs/performance/M3-facts.md);
user stories: [M3](docs/user-stories/M3-structured-memory.md).

### [A6] Semantic answer cache

A question already asked, even in other words, gets the answer already given
without calling the chat model again. The answer is marked "↺ depuis le
cache", with the original question and its date.

```
> Comment je lance les tests du projet ?
↺ depuis le cache · question « Comment lancer les tests du projet ? » du 18/10 à 19:56 (similarité 0.92)
```

| Command | Effect |
|---|---|
| `/again` | Asks the model the last question again and replaces the cached answer |
| `/context` | Shows the exact messages that will be sent to the model, their estimated tokens, `num_ctx`, the budget and the generation settings (ADR-0058) |
| `/cache` | Cached answers, times served, time saved |
| `/cache clear` | Empties the project's cache |
| `sensai --cache` | Turns the cache on (or `"cache": true` in `config.json`); off by default since [ADR-0056](docs/decisions/0056-scope-review-features-to-drop-or-limit.md) |

The cache is **off by default** (for one developer, few questions repeat) and
**cautious** when turned on. It compares questions by embeddings (bge-m3,
threshold 0.90), refuses two questions where an action or a name differs
("activer" and "désactiver", `purge_sessions` and `purge_facts`), and forgets
an answer as soon as a file it read changes. It ignores questions that depend
on the conversation ("and then?") and turns where the agent wrote or ran
something. Measured: none of the 48 traps served, 7 rephrasings out of 39
served, in 1.06 s instead of 16.8 s. Stored in `~/.sensai/cache.db`. Choice:
[ADR-0033](docs/decisions/0033-cache-semantique-prudent.md); measurements and
real run: [docs/performance/A6-cache.md](docs/performance/A6-cache.md); user
stories: [A6](docs/user-stories/A6-semantic-cache.md).

### [X5] Scheduled tasks

`sensai-schedule` replays agent tasks at a fixed interval, unattended
(started by cron, a systemd timer or `loop`). Nobody can answer a
confirmation: writing and running are always refused, reading and web search
go through.

```bash
sensai-schedule add resume-jour --every 1d --prompt "Résume les TODO du projet."
sensai-schedule run-due          # joue les tâches échues puis s'arrête (pour cron)
sensai-schedule history resume-jour
```

The same commands can be typed in the chat with `/schedule` (except `loop`,
which never returns): `/schedule list`, `/schedule run resume-jour`.
You can also just ask the agent ("summarise the TODOs every morning"): it proposes a
`schedule_task` that is saved only after you approve it
([ADR-0052](docs/decisions/0052-schedule-task-tool.md)).

Full guide (cron, systemd, files, limits):
[docs/architecture/scheduling.md](docs/architecture/scheduling.md); choice:
[ADR-0016](docs/decisions/0016-planification-des-taches.md).

### [EV4] Adversarial tests (team tool)

85 attacks replayed against the existing defences (injections, trapped paths,
malformed arguments, secret leaks…), without a model. Known gaps are strict
expected failures: fixing a gap makes the suite fail until it is
reclassified.

```bash
pytest tests/adversarial -q                 # 75 pass, 19 known gaps
python scripts/adversarial_run.py           # régénère le tableau des résultats
```

The corpus lives in `src/sensai/eval/adversarial.py` so the web server can
rerun it: with `sensai-web`, the Quality page shows the real results and a
"Relancer les attaques" button (`POST /api/quality/adversarial/run`, no model).

Report (what holds, what breaks, what to strengthen):
[docs/securite/EV4-tests-adversariaux.md](docs/securite/EV4-tests-adversariaux.md);
choice: [ADR-0018](docs/decisions/0018-ecarts-adversariaux-xfail-stricts.md).

### Other delivered features

These features are in `main`; their details are in their ADR and user
stories:
- **[A2] Multi-agent orchestration**: `delegate_task` (a sub-agent) and
  `team_task` (explorer, developer, reviewer)
  ([ADR-0038](docs/decisions/0038-agents-specialises-et-relais.md),
  [user stories](docs/user-stories/A2-multi-agent-orchestration.md)).
- **[A5] Personas**: configurable profiles, switchable during a session, in
  the CLI ([ADR-0042](docs/decisions/0042-personas-configurables.md),
  [ADR-0043](docs/decisions/0043-persona-enhancements.md)) and, per
  conversation, in the web ([ADR-0054](docs/decisions/0054-personas-in-the-web.md)).
- **[A4] Prompt versions in the web**: the Prompts page reads the real
  registry and can try a system version in one conversation
  ([ADR-0055](docs/decisions/0055-prompt-versions-in-the-web.md)).
- **[A7] Automatic few-shot examples**
  ([ADR-0044](docs/decisions/0044-automatic-few-shot.md)).
- **[M2] Token budget and sliding summary**
  ([ADR-0045](docs/decisions/0045-token-budget-sliding-summary.md)).
- **[T1] MCP client**: servers declared in `config.json`, one agent tool per
  MCP tool ([ADR-0041](docs/decisions/0041-client-mcp-maison.md)).
- **[T5] Structured output** with a JSON schema
  ([ADR-0039](docs/decisions/0039-sortie-structuree-fondee-sur-le-projet.md)).
- **[X2] Branches**: edit a message to create a variant, stop an answer
  ([user stories](docs/user-stories/X2-branching.md)).
- **[X3] Export** as JSON, Markdown or PDF, and share links (see X1).
- **[X4] Questions by form** with `ask_user`, in the CLI and the web.

## Known limits / not done yet

- **Web interface, real model**: the web additions merged on 2026-10-29 and
  2026-10-31 were tried with `qwen3-coder:30b` on 2026-11-01
  ([trial](docs/performance/essais/essai-2026-11-01.md)). The project index not being refreshed during a session
  (finding 1) is fixed (PR #108). Findings 2–6 were then addressed and re-checked with the
  real model (see "Re-check after the fixes" in the trial):
  - `team_task`: a file created in the wrong place is sent back and never validated (fixed).
  - Language preference vs a French few-shot example: fixed on 2026-11-01 afternoon
    (profile last in the prompt, preferences repeated next to the example, example not
    attached when the question is its own); re-checked once per question with the real model.
  - Facts saved in a deleted conversation stay; they can now be forgotten from the
    Memory page, and the delete confirmation says so (fact history keeps a trace).
  - Answer text split by tool calls is saved as paragraphs, a rewritten or rephrased part
    only once (fixed); the live stream still shows both parts as they arrive.
  - Inventing a value never read: system prompt v3 forbids it; re-checked once, the model
    said it did not know (mitigated: depends on the model).
- **Full trial of 2026-11-01 afternoon** ([report](docs/performance/essais/essai-2026-11-01-soir.md)):
  every feature passed with the real model (API, global run, browser). The facts and
  state-document blocks no longer push the model to call `recall_facts`,
  `update_state` or `save_fact` for a simple question. Each check is one try: the
  model's behaviour can still vary.
- **Web additions of 2026-10-29 (branch `lot-d/web-real-features`)**: token
  counts are estimates
  (characters / 4); sub-agent step output is cut at 600 characters.
- **A7 visible in the web** (2026-11-01): the Prompts page lists the real
  few-shot examples (`GET /api/fewshot`) and the chat shows which example
  inspired an answer. Detail: [simule-vs-reel.md](docs/architecture/web/simule-vs-reel.md).
- **Personas (A5) and prompt versions (A4) in the web** (Lot A, 2026-11-01, checked
  with `qwen3-coder:30b`): the persona and the prompt trial are per conversation and
  held in server memory, not saved. Keyword routing and session-only personas were removed (ADR-0056).
  Activating a prompt version for everyone stays `sensai-prompt use`; the web never
  writes the registry.
- **Scheduler (X5) in the web**: the Planning page edits the tasks, but only
  `sensai-schedule loop` (or `run-due`) runs them; the web server runs none.
- **Terminal-only chat commands**: `/schedule` and `/eval` typed in the web chat
  answer that they are used in the terminal (`TERMINAL_ONLY` in `src/sensai/web/runtime.py`).
- **Evaluation (EV1) in the web**: on demand only (one model call per click),
  never automatic at each turn.
- **MCP (T1)**: tried with the repo's test server and, on 2026-11-01, with the
  published `mcp-server-time` server (issue #45): the model called it by itself when
  `web_search` was disabled.
- **Logging (EV3)**: the turn journal (`<data_dir>/journal.db`,
  [ADR-0053](docs/decisions/0053-server-side-turn-journal.md)) is tested with a
  scripted model and was checked with the real model on 2026-11-01; durations are wall-clock (a
  tool's duration includes the user's confirmation time); the CLI does not record
  sub-agent tool calls yet.
- **Structured output (T5)** is a terminal command (`/structured`), not a web
  feature; the Quality page only points to it.
- **Adversarial gaps**: 19 known gaps of the EV4 corpus remain (obfuscated
  injections and secrets, some sensitive files, look-alike search results);
  see the [backlog](docs/backlog.md).

Tracking: the repo's GitHub issues.

## Testing

```bash
pytest -q                              # sans modèle ; les tests Docker sont ignorés sans Docker
pytest -m docker -q                    # isolation des sandboxes sur de vrais conteneurs
python scripts/essai_outils.py --web   # essai réel des outils à travers la passerelle
(cd frontend && npm test)              # interface web
```

## Team

| Lot | Folders | Person |
|---|---|---|
| A — Brain | `core/` (agent, tool registry, Ollama client) | Fresnel |
| B — Hands | `execution/`, `tools/sandbox_tool.py` | Méric |
| C — Memory | `knowledge/`, `tools/rag_tool.py` | Ridwane |
| D — Interface & integrations | `web/`, `observability/`, `tools/mcp_tool.py` | Valentino (GitHub: Christopher142769) |

The web interface moved out of Lot C and the MCP tool out of Lot A: see
[ADR-0005](docs/decisions/0005-interface-web-facade.md).

Detailed planning and tasks: see the ClickUp list "Sensai — Planning".
