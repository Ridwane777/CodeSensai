# ADR-0049 — Web interface (X1): answers rendered by a small hand-written Markdown renderer, not a library

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-10-29
- **Deciders**: Ridwane (Lot C), on behalf of Lot D (Valentino) — to be confirmed by the team
- **Lot concerned**: D (`frontend/src/features/chat/markdown.tsx`)

## Context

The agent answers in Markdown (headings, lists, code blocks, links). The
interface only rendered bold, inline code and uncoloured code blocks. Model
output is untrusted text: it can contain HTML or `javascript:` links, written
by the model or copied from a file or a web page it read.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| **Hand-written renderer for the subset the model uses** (chosen) | No new dependency; everything goes through React, so HTML is never interpreted; only `http(s)` links; reuses the existing Python highlighter | Partial Markdown: no tables, no nested lists, no images; we maintain it |
| `react-markdown` + `remark-gfm` + a highlighter (Prism/Shiki) | Full CommonMark/GFM, tables, many languages | Several new dependencies and a bigger bundle; safe by default but its options (raw HTML, URL transform) must stay locked; a new entry in `docs/dependances.md` |
| `marked` + `dangerouslySetInnerHTML` + DOMPurify | Fast and complete | Inserts HTML: safety depends on the sanitizer configuration |

## Decision

`markdown.tsx`: headings, bullet and numbered lists, quotes, paragraphs, bold,
italic, inline code, `http(s)` links (`target=_blank`, `rel=noopener noreferrer
nofollow`) and fenced code blocks with a "Copier" button; Python and shell
blocks are coloured with the existing highlighter (`features/code/syntax.tsx`).
No raw HTML is ever inserted.

## Consequences

- ✅ No new dependency, no HTML injection path, same look as the rest of the interface.
- ❌ Tables, nested lists, images and colouring for languages other than Python/shell are not rendered (they stay readable as text).
- ❌ We maintain a parser: an unusual Markdown construct can render oddly.
- Follow-up: switch to `react-markdown` + `remark-gfm` (with raw HTML off) if answers with tables become common; that would need its own ADR and a line in `docs/dependances.md`.
