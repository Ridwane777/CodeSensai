# ADR-0030 - Structured memory: "entity, attribute, value" facts maintained by the agent itself

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-17
- **Deciders**: Ridwane (Workstream C)
- **Workstream**: C; A affected (`cli.py`: tools, system prompt, `/facts` command); B affected (two tools go through the gateway)

## Context
[M3] External Structured Memory (issue #57, mandatory since ADR-0008):
memory moves into a real database; the agent itself reads, writes and updates
structured records (facts, entities, relations) through
CRUD operations, over time, exposed as tools. User stories:
[M3-structured-memory.md](../user-stories/M3-structured-memory.md).

What already exists and is not enough:
- M1 keeps the raw conversation (purged after 30 days) and a profile that
  only the user fills in (`/remember`);
- M4 (`SENSAI.md`, ADR-0029) is a prose report, meant to be read.

Neither can retrieve a **specific fact** ("which Redis version
does auth use?") weeks later. Constraints: every write goes
through the gateway (ADR-0006); memory is re-read by the model in every
session, which makes it a lasting injection target ("memory
poisoning").

**Division of roles**: the agent (the model) **decides** what to remember or
look up and requests it through tool calling; the gateway checks; the
**tools execute** the operation in SQLite, with parameterized queries.
The model never writes SQL and never touches the database.

## Considered options

**1. Data model**

| Option | Pros | Cons |
| --- | --- | --- |
| **Entity, attribute, value triples in a SQLite table** (chosen) | Classic format for fact memories and knowledge graphs; a single table covers facts and relations (a relation is a fact whose value is an entity); simple lookup in both directions | No enforced schema: the model may name the same attribute two ways |
| Three tables: entities, attributes, relations | More rigorous | More code and tools, more model errors |
| Free-text notes with tags | Very flexible | No longer "structured": contradicts the catalog, and redoes M4 |

**2. Tools and confirmation**

| Option | Pros | Cons |
| --- | --- | --- |
| **`save_fact` (`write` risk, confirmed) and `recall_facts` (`read` risk); deletion reserved for the user** (chosen) | The minimum for the three user stories; looking up never interrupts; no fact enters memory without consent | One confirmation per saved fact |
| `save_fact` declared `read` | Smooth | A web page or a file read could plant a false fact, served again in every session |
| Four CRUD tools, deletion included | The most complete | An agent that erases its memories is hard to control; `replace` already covers modification |

**3. What the agent knows at startup**

| Option | Pros | Cons |
| --- | --- | --- |
| **The list of known entities (50 at most) in the system prompt; details through `recall_facts`** (chosen) | Lightweight whatever the memory size; the model knows it has something on "auth" and thinks to look it up | One more tool call |
| All facts in the prompt | No tool call | Does not scale: memory grows without a time limit |
| Facts related to each question added automatically | Nothing for the model to do | Guessing related facts is fragile and adds noise |

**4. What the user does themselves**

| Option | Pros | Cons |
| --- | --- | --- |
| **`/facts` command in the chat** (chosen) | Without leaving the chat, never seen by the model; same logic as `/state`, `/profile` | Nothing outside the chat |
| Separate `sensai-facts` command | Scriptable | You have to leave the chat; it is a working memory, not a team tool |

## Decision
Facts are stored in `~/.sensai/memory.db` (SQLite, folder `700`,
file `600`), attached to the project path, with no automatic purge. A
fact is a triple (entity, attribute, value); names are compared
ignoring case and extra whitespace, and a given triple exists
only once. Every creation, modification and deletion is kept in
a history (old and new value, date).

Tools offered to the agent:
- `save_fact(entity, attribute, value, mode)`, `write` risk: `replace`
  replaces the attribute's value(s), `add` adds a value (for
  multi-valued relations). The confirmation shows the fact, and
  the old value if there is one. Empty or overly long fields are refused.
- `recall_facts(entity, attribute, value)`, `read` risk, at least one criterion:
  everything about an entity, a specific attribute, or the entities with the given
  value (inverse relations). With no result, the response says so.

Tool descriptions fit in one sentence and the write tool
is called `save_fact`: with a long description or the name `remember_fact`,
qwen3-coder wrote its calls as text instead of making them (4 structured
calls out of 12 versus 8 out of 12, measured on the pod on 2026-10-17). The usage
instructions are in the system prompt.

The system prompt contains the list of known entities (the 50 most
recently modified), framed as data, re-read on every message; it
asks to remember only lasting, important facts. In a scheduled
task (X5), `recall_facts` works and `save_fact` is refused.

In the chat: `/facts` (entities), `/facts <entity>` (its facts),
`/facts forget <entity> [attribute] [value]` (deletion; asks for
confirmation when it targets a whole entity), `/facts history <entity>`.

## Consequences
- ✅ The agent retrieves a specific fact weeks later, in any
  session of the project, and cites it.
- ✅ No fact enters memory without consent, and the agent cannot erase
  anything: an injected false fact does not settle in silently.
- ✅ The prompt stays light: only entity names are in it.
- ❌ One confirmation per saved fact: if the agent remembers too many
  details, it gets tedious. To be measured during the trial run.
- ❌ No schema: `version_redis` and `redis_version` can coexist.
  Showing existing attributes in `recall_facts` limits the problem without
  removing it.
- ❌ No automatic purge: memory keeps personal data
  (people's names, internal choices) until the user erases it
  (`/facts forget` or deleting the file), to be described in the legal
  docs.
- ❌ The entity list in the prompt may contain an injected name: it is
  framed as data, which limits the risk without removing it (same
  limit as EV4-OUT-14).
- Follow-up: tests (no duplicates, `replace` and `add`, history, per-project
  memory, inverse relations, refusals); trial run on the pod (remember a fact,
  retrieve it in a new session, correct it, forget it).
