# ADR-0010 — Prompt versioning: immutable versions in the repository, "active" bookmark

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-12
- **Deciders**: Ridwane NICO (Workstream C), to be approved with Workstream A (shared files)
- **Workstream**: C (impacts A: `config.py`, `config.json`, `prompts/`)

## Context
Feature [A4] Prompt Versioning (mandatory since ADR-0008) must make it
possible to show the history of system prompts and go back to an old
version in one command (ClickUp Definition of Done). It serves **the team
building the agent**, not the end user: "you will iterate on system prompts
(ReAct, guardrails, persona) throughout the project anyway — might as well
treat them as versioned, comparable and rollback-able artifacts". Feature
A7 (Workstream A) can build on it. Detailed needs:
[A4 user stories](../user-stories/A4-prompt-versioning.md).

Real case: M1's memory prompt (`prompts/memory_prompt.txt`), added after the
trial runs, changed the model's answers
([M1 trial runs](../performance/M1-sessions.md)).

State checked on 2026-10-12 across all remote branches:
- `prompts/system_prompt.txt` is loaded by `config.py` everywhere;
- `prompts/memory_prompt.txt` is loaded on the M1 and R1 branches;
- `prompts/react_prompt.txt` is loaded nowhere, including on
  `lot-a/boucle-react` (the loop uses native tool calling);
- no "guardrails" prompt exists (`lot-b/guardrails` has none).

**Industry practice** (Langfuse, Arize, Agenta, PromptLayer, Maxim; sources
at the end of the document): a **version is immutable** and identified by a
number or a hash; a **label** (`production`…) is a **movable pointer**; the
application loads the pointed version, and rolling back means **moving the
pointer**, without redeploying. Each version keeps who created it, when and
why. Teams often start with prompts in git, then add such a registry when
rolling back requires a revert and a redeploy.

Constraints:
- `config.py` and `prompts/system_prompt.txt` are shared with Workstream A;
  the other branches must not break before the merge.
- No new dependency.

## Considered options

**1. Where versions live**

| Option | Pros | Cons |
| --- | --- | --- |
| **In the repository** (chosen): one folder per prompt (`prompts/system/v1.txt`…) and an index `prompts/versions.json` | Shared by the team, reviewed in PRs, readable without a tool, loadable from code (A7) | One more file per version in the repository |
| Local database (SQLite in `~/.sensai/`, like M1) | Immediate rollback | Each developer would have their own history: a teammate's versions would be invisible (contrary to US-A4-1) |
| Git only (`git log` and `git diff` on `prompts/`) | Nothing to store | Only works in a clone; an uncommitted change is not a version; versions are not objects the code (A7) can simply load |

**2. What the agent reads**

| Option | Pros | Cons |
| --- | --- | --- |
| **The version carrying the bookmark** (`"active"` in the index) (chosen) | Matches industry practice: rolling back only moves the bookmark, nothing is copied or erased | Requires changing `config.py` (Workstream A) |
| Keep `system_prompt.txt` as the file read, and copy a version into it to roll back | `config.py` unchanged | Duplicated text; you no longer know which version is in service. Chosen at first, abandoned after researching industry practice |
| Automatic version creation on every change detected at launch | No action needed | Noisy history, without descriptions; conflicts when two branches create the same version |

**3. Identifying a version**

| Option | Pros | Cons |
| --- | --- | --- |
| **A number** (`v1`, `v2`…), with date, author, description and sha256 hash in the index (chosen) | Readable and short to type. The hash does not identify: it lets `sensai-prompt check` (and CI) detect a version modified after being stored — without it, "a version is never modified" would just be a convention (added while writing the tests) | Two branches that each create a `v4` produce a git conflict in `versions.json`: renumber one of them |
| Date and time (`2026-10-12_1724`) | No collision | Long to type |
| sha256 hash as identifier | No collision | Unreadable; only useful if each machine kept its own history |

**4. Which prompts to version**

| Option | Pros | Cons |
| --- | --- | --- |
| **`system` and `memory`, with a generic mechanism** (adding a prompt = one line) (chosen) | The only two prompts that actually influence the agent | — |
| `system` only | The letter of the DoD | No history for the memory prompt, the real case |
| Include `react_prompt.txt` | Complete in appearance | This file has no effect: we would be versioning an unused file |

**5. Commands**

| Option | Pros | Cons |
| --- | --- | --- |
| **A separate command, `sensai-prompt`**, declared in `pyproject.toml` (chosen) | Team tool used like `git`; needs neither Ollama nor the agent; usable in scripts or CI; does not touch Workstream A's parser | One more command to know |
| In-session commands (`/prompt …`), like M1 | Same style as M1 | You would have to launch the agent to view a history |
| Subcommands `sensai prompt …` | A single command | Would require reorganizing the `config.py` parser, shared with Workstream A |

## Decision
- Versions live in `prompts/<name>/vN.txt`; the index
  `prompts/versions.json` keeps, for each prompt, the `active` bookmark and
  the list of versions (`id`, `date`, `author`, `description`, `sha256`):

  ```json
  {
    "system": {
      "active": "v2",
      "versions": [
        {"id": "v1", "date": "2026-09-22", "author": "…", "description": "initial prompt", "sha256": "a1dc…"},
        {"id": "v2", "date": "2026-10-12", "author": "…", "description": "clarifies the format", "sha256": "…"}
      ]
    },
    "memory": {"active": "v1", "versions": ["…"]}
  }
  ```

- A stored version is never modified or deleted; a test
  (`tests/test_prompts_registry.py`) checks the repository's registry in CI.
- The agent loads the `active` version of each prompt. If `versions.json` is
  missing, it reads `prompts/system_prompt.txt` and
  `prompts/memory_prompt.txt` as before. The existing
  `--system-prompt <file>` option keeps priority: it is used to try a draft.
- At launch, `sensai` displays the versions in use ("prompts: system v2,
  memory v1").
- Migration: the current content of `system_prompt.txt` and
  `memory_prompt.txt` becomes `v1` of each prompt; both files are then
  deleted, so the text exists in only one place. Date and author of each
  `v1`: those of the last commit of the original file. The
  `system_prompt_path` key is removed from the repository's `config.json`:
  it pointed to the old file, and an explicit path takes precedence over the
  registry.
- Commands:

  ```
  sensai-prompt history <prompt>                      versions: no., date, author, description, (active)   US-A4-1
  sensai-prompt show <prompt> [version]               content of a version (the active one by default)
  sensai-prompt diff <prompt> <v1> [v2]               line-by-line differences (v2 = the active one)       US-A4-1
  sensai-prompt save <prompt> <file> "description"    stores the file as a new version                     US-A4-2
  sensai-prompt use <prompt> <version>                moves the bookmark                                   US-A4-3
  sensai-prompt check                                 consistency: numbers, files, bookmarks, hashes
  ```

- `save` does not move the bookmark (store first, then put into service) and
  refuses a text identical to an existing version. The author is read from
  `git config user.name`.
- Differences computed with `difflib` (standard library).

Typical flow for the team:

```
sensai-prompt show system > draft.txt                     start from the text in service
sensai --system-prompt draft.txt                          try it
sensai-prompt save system draft.txt "clarifies X"         it becomes v3
sensai-prompt diff system v2 v3                           compare
sensai-prompt use system v3                               the agent reads v3
sensai-prompt use system v2                               roll back if needed
```

## Consequences
- ✅ Checked with a real model (`qwen3:8b`, 2026-10-12): switching to a v2
  that mandates French makes the agent answer in French, and
  `sensai-prompt use system v1` restores English
  ([real trial run](../performance/A4-prompts.md)).
- ✅ Rolling back = moving a bookmark: one command, no text copied, no
  version lost (DoD).
- ✅ History shared by the team, reviewed in PRs, with who, when and why for
  each version.
- ✅ Versions are objects loadable by code: A7 can try or compare versions
  without going through git.
- ✅ No new dependency; the other branches keep working thanks to the
  fallback to the old files.
- ❌ **Changes `config.py` and `config.json`, and deletes
  `prompts/system_prompt.txt`**, shared with Workstream A: to be approved
  with Fresnel before the merge. A personal `config.json` that keeps
  `system_prompt_path` bypasses the registry (an explicit path takes
  precedence).
- ❌ Moving the bookmark changes `versions.json`: for it to apply to the
  whole team, it must be committed (a personal trial is done without a
  commit).
- ❌ Two branches that create the same version produce a merge conflict, to
  be resolved by hand by renumbering.
- ❌ The model and its parameters are not versioned with the prompt: they
  stay in `config.json`. An answer depends on both.
- ❌ Outside A4, to flag to the team: `react_prompt.txt` is used nowhere (to
  wire or delete); the `prompts/` files are not included in the installed
  package (checked by building the wheel), a problem that predates A4.
- ❌ Depends on M1's memory prompt: the branch is stacked on the M1 and R1
  branches, to rebase after they are merged.

## Planned evolutions
The feature will evolve with contributions from the other workstreams:
version the ReAct prompt when Workstream A wires it, rely on EV1 to attach
evaluation results to each version, and let A7 create versions.

## Sources
- [Langfuse — Prompt Version Control](https://langfuse.com/docs/prompt-management/features/prompt-version-control)
- [Arize — What Is Prompt Versioning?](https://arize.com/glossary/prompt-versioning/)
- [Agenta — Git vs. Prompt Management Tools](https://agenta.ai/blog/git-vs-prompt-management-tools)
- [Agenta — Prompt Versioning: The Complete Guide](https://agenta.ai/blog/prompt-versioning-guide)
- [PromptLayer — How to version prompts in LLM apps](https://blog.promptlayer.com/how-to-version-prompts-in-llm-apps/)
- [Maxim — Prompt Versioning: Best Practices for AI Engineering Teams](https://www.getmaxim.ai/articles/prompt-versioning-best-practices-for-ai-engineering-teams/)
- [Hamel Husain — How should I version and manage prompts?](https://hamel.dev/blog/posts/evals-faq/how-should-i-version-and-manage-prompts.html)
