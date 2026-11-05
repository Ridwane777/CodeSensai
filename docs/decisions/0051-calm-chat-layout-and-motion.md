# ADR-0051 — Calm chat: wider column, folded side panel, smooth motion and a visible "working" indicator

- **Status**: Accepted (2026-11-01, validated by the team)
- **Date**: 2026-10-31
- **Deciders**: Valentino (Lot D), pending the team's agreement
- **Lot**: D (web interface); no impact on Lots A, B, C: no API route, event or Python code changes

## Context

Valentino tried the web interface on his own computer on 2026-10-31 and wrote
down the frictions he felt, compared with the chat interfaces he uses every
day:

1. **Too much at once.** Opening the chat showed a 3D scene, two animated code
   cards that followed the mouse, a title that arrived word by word, and a
   button ("Activer la conversation") to click before the input field even
   appeared.
2. **Things moved all the time.** Several animations were deliberately
   "stop motion" (`steps()` timing): the agent's avatar shook while it worked,
   a light swept across the input field and the reasoning block, and a code
   rain in the background followed the mouse.
3. **Not fluid.** At each streamed token the page started a new *smooth* scroll
   to the bottom, so the page jerked during an answer, and it pulled the reader
   down even when they had scrolled up to read.
4. **Unclear when the agent works.** The only signal was "· réfléchit" in small
   grey text and a "● en direct" label: there was no clear indicator showing
   that the agent was busy and for how long.
5. **Too narrow in the centre.** The conversation sat in a 48rem column next to
   a 22rem side panel (Artefact / Sources) that was always open, inside a page
   capped at 80rem.

## Options considered

| Option | Pros | Cons |
| --- | --- | --- |
| Keep the layout, only slow the animations down | Smallest change | Points 1, 4 and 5 stay; the activation gate still delays the first message |
| Copy a general-purpose assistant layout fully (no side panel at all) | Familiar | Loses the Artefact and Sources panels, which show features M4 and C2 of the subject |
| **Calm layout: input on the welcome screen, wider column, folded panel, smooth motion, one clear indicator** | Fixes the five points; keeps every feature reachable | The welcome screen loses its 3D hero; the panel's content is one click away |

## Decision

The chat page follows the third option:

- **Welcome**: a short greeting, the input field focused and ready, and the
  suggestions. No activation button, no 3D scene, no code cards, a single
  fade-in.
- **Layout**: the chat uses the full width to the right of the sidebar; the
  conversation column is 56rem (`max-w-4xl`); the input sticks to the bottom
  of the screen with a fade so messages slide under it; the token gauge (M2)
  moves under the input.
- **Side panel**: folded by default and opened by an "Artefact · Sources"
  button. A dot on the button signals new content. The choice is remembered in
  the browser (`localStorage`). On small screens the panel is a drawer.
- **Motion**: every `steps()` animation becomes a smooth one (`ease`, `linear`);
  the avatar no longer shakes; the sweeping light and the chat's code rain
  are removed. `prefers-reduced-motion` still turns every animation off.
- **"Working" indicator** (`ThinkingIndicator`): a slowly rotating star, a
  shimmering label saying what the agent does ("Réflexion", "Utilise
  read_file", "Rédaction") and the seconds elapsed. The reasoning block stays
  open during the turn, then folds with a slide animation and shows its
  duration ("Raisonnement · 2 étapes · 9 s").
- **Scrolling**: the page follows the answer only while the reader is at the
  bottom; a "↓ Revenir en bas" button appears when they scroll up. A new
  message scrolls smoothly; text growing inside a message follows instantly,
  without jerks.

**Home page** (second pass the same day, after Valentino found it "too
scattered": with the left sidebar, the full-screen poster cut the title and
the cards overlapped): a two-column hero that stays inside the content area —
tagline, a "first question" field that opens the chat, three starters and the
"Lancer la démo" / "Ouvrir le chat" button on the left; the AI portrait in a
frame with one still terminal card on the right. No giant name, no code rain,
no parallax.

**Home page, third pass** (same evening: still "too complicated", "give it more
room", with a reference screenshot of a chat product's landing page and the
request "no AI"): the two-column hero is replaced by a single dark stage that
fills the screen — the name "CodeSensei" very large and translucent, one
rounded question field over it, a warm halo of light on the right that
breathes slowly, a short sentence and two buttons at the bottom. The AI
portrait, the terminal card and the starters are removed from the home page
(the starters stay on the chat's welcome screen). The stage follows the theme: a dark
stage with a white halo in the dark theme, a warm cream stage with an amber
halo and dark letters in the light theme; its colours are CSS variables
(`--stage-*`) and its bottom fades into the page background.

**Real agent by default in development**: `npm run dev` relays `/api` and
`/share` to `sensai-web` (Vite proxy), so the dev interface no longer falls
back to the demo when the server runs. With the server, the chat's
suggestions are questions about the project, not demo scenarios; the persona
selector is hidden (the server has no personas) and the Agents page shows the
real agent. A turn now ends when the server **closes** the stream, not on the
`done` event: the server saves the conversation and frees the session between
the two, so ending on `done` listed the conversations too early and could get
a 409 on an immediate follow-up.

The same branch also connects the last two server routes that the interface
did not use: **revoking a share link** (`POST /api/shares/{token}/revoke`,
"Révoquer le lien" button) and the **server export** with secrets masked
(`GET /api/sessions/{id}/export`, "Conversation du serveur" buttons on the
Export page).

## Consequences

- ✅ The first message can be typed as soon as the chat opens; nothing moves
  unless the agent works.
- ✅ The reader always sees *that* the agent works, *what* it does and *for how
  long*, without reading the raw steps.
- ✅ Every server route of `sensai-web` now has a control in the interface.
- ❌ The welcome screen loses the 3D hero and the animated code cards that
  showed the "agent that reads code" idea; they stay on the landing page
  (`/`) only.
- ❌ The home page no longer shows *what* the agent does (portrait, terminal
  card, examples): a visitor has to read the sentence at the bottom or open
  the chat to understand the product.
- ❌ The Artefact and Sources panels, which show M4 and C2, are hidden by
  default: a demo must open them (one click), and someone who never clicks
  the button may miss them.
- ❌ The elapsed time is measured in the browser, from the moment the turn
  appears, not by the server; it includes the network delay.
- Follow-up: frontend tests (`frontend/tests/chat.test.tsx`,
  `cards.test.tsx`, `panels.test.tsx`, `export.test.tsx`,
  `httpEngine.test.ts`); checked in a browser with the simulated engine on
  desktop (1440×900) and phone (375×812) widths, then against a real
  `sensai-web` through the Vite proxy with the only local model available,
  `granite3.1-moe` (3.3B, `--no-rag`): connection, home question, streaming,
  indicator, follow-up without 409, sidebar and Memory lists, Agents page.
  **Not yet tried with `qwen3-coder:30b`**, the project's model. To revisit if users still find the page
  too busy, or if demos keep missing the panels (then open the panel
  automatically the first time an artefact appears).
