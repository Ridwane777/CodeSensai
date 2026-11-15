# How we work on this repository

Read once, before your first commit. These rules are not decoration: `main`
is the branch we demo from, and one person pushing broken code to it costs
us an evening.

## The main rule

**Nobody pushes directly to `main`.** Changes land through a reviewed Pull
Request. If the repository's admin settings do not let us enforce it
technically, the rule holds because we respect it.

## The work cycle

```bash
git checkout main
git pull
git checkout -b lot-a/react-loop
# ... work, commits ...
git push -u origin lot-a/react-loop
```

Then open the Pull Request on GitHub.

**Branch naming:** `lot-<a|b|c|d>/<short-topic>`, where the letter is the
workstream. The prefix tells who is working without opening the branch -
`lot-b/sandbox-docker`, `lot-c/rag-ingestion`, `lot-d/api-web`.

**Before pushing**, if `main` has moved in the meantime:

```bash
git pull --rebase origin main
```

The rebase replays your work on top of the up-to-date `main`. You discover
conflicts locally, not in the PR in front of everyone, and the history stays
readable.

## Reviews

One approval is enough, then the author merges. With four people, requiring
two reviewers blocks everyone.

**Who reviews:** `.github/CODEOWNERS` says so, and GitHub requests it
automatically. The logic: whoever touches a shared contract gets it reviewed
by the contract's owner. For the rest, within your own folder, a quick review
by anyone is enough.

`src/sensai/core/tools.py` is the sensitive case: a change there breaks the
other three workstreams. It always goes through Workstream A.

## Short branches

The longer a branch lives, the further `main` moves without it, and the
higher the risk of touching the same lines as someone else. Split the work:
"the MCP client connects", then "the MCP client calls a tool" - not one huge
PR.

## What must pass before requesting a review

```bash
pytest -q
ruff check src tests
```

CI (`.github/workflows/ci.yml`) runs both on every PR. A red PR is not
merged.

If your change adds a guardrail, **add the test that fails when it is
removed** - otherwise someone will "simplify" it in three weeks without
understanding what it was for.

## Architecture decisions

When a structural choice is made - a tool we adopt, an approach we reject -
it is written in `docs/decisions/`, from `TEMPLATE.md`. One file per
decision, numbered, never rewritten: if we change our minds, we create a new
one that supersedes the old one. Each ADR adds its row to the index
`docs/decisions/README.md`, and its "Consequences" section also says what we
lose (at least one ❌).

ADRs are only part of the project file (legal, performance, costs,
retrospective, business, user stories): see the map
`docs/README.md`.

Each ADR carries a `Status`: `proposed` until the team has decided,
`accepted` afterwards. Do not present as settled something that still awaits
agreement.

What deserves an ADR: a decision that is costly to undo, or one where someone
will ask "why did they do that?" in two months. Choosing a variable name does
not.

## Code conventions

- **Comments in English**, like the rest of the code, explaining the
  **why** - especially in security logic. That is what stops a future
  contributor from removing a critical check by accident.
- **Commit messages in English**, in the existing format:
  `feat(scope): ...`, `docs(scope): ...`, `chore(scope): ...`.
- Write like the surrounding file: same style, same level of commenting.

## What we never commit

No API key, no `.env`, no password, no private pod address. `.gitignore`
covers part of it, not all of it - check the diff before pushing.

If a secret leaks anyway: tell the team immediately, and consider the key
compromised. Removing it from a commit does not remove it from the history.
