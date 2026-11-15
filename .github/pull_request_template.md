## What this changes

<!-- One or two sentences. What a reviewer needs to understand before reading the code. -->

## Workstream and decision involved

<!-- Workstream A / B / C / D - and the ADR if the PR applies or challenges a decision
     (docs/decisions/). Write "none" if it touches no decision. -->

## How to verify

<!-- The command to run, or what to look at to see it works. -->

## Before requesting a review

- [ ] `pytest -q` passes
- [ ] `ruff check src tests` reports nothing
- [ ] the branch is up to date with `main` (`git pull --rebase origin main`)
- [ ] no secret, API key or `.env` in the diff
- [ ] if this PR settles an architecture choice, the matching ADR is written
