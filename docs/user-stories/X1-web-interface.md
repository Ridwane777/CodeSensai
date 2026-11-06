# User stories — [X1] Web interface

Interface: `frontend/`.

CodeSensei scenario: Camille takes over a Python project and wants to follow,
correct and keep a record of what the agent does, without reading the code.

**Validation status**: these criteria were first checked **on the simulated
engine** (tests in `frontend/tests/`, [ADR-0020](../decisions/0020-interface-web-simulee.md)).
On 2026-10-18, the interface was connected to the real agent through `sensai-web`
([ADR-0035](../decisions/0035-serveur-web-reel.md)) and tried in a browser
with `qwen3-coder:30b` ([web-reel.md](../performance/web-reel.md)). Each story
carries its status:
✅ checked with the real agent · ◐ partly · 🎭 still simulated · ⏳ not checked yet.
Details per function: [simule-vs-reel.md](../architecture/web/simule-vs-reel.md).

The other features staged in the demo (A1, A3, M2, T2…) have their own
story files.

Other user stories for the interface: [README.md](README.md).

---

## US-X1-1 — Follow an answer and its reasoning live
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ◐ Partly. **Real, checked in the browser**: the answer arrives as it is written, with a cursor; each step shows the tool, its arguments, the result and the duration (e.g. `read_file`, 21 ms); a failure is shown as "✗ Échec"; the block collapses and expands. **Simulated**: the token bar stays at 0, because the server does not send the usage yet. The badge now shows "Agent réel · modèle" when the interface is connected, and "Moteur simulé" otherwise.

**As** Camille, the developer who hands a task to the agent,
**I want** to see the answer arrive progressively, along with each reasoning step (thought, tool called, result),
**so that** I understand what the agent does and can correct it early if it goes wrong.

**Acceptance criteria:**
- The answer is shown word by word, with a cursor until it is finished.
- Each step shows the thought, the tool and its arguments, the result and the duration in milliseconds; a failure is reported as such.
- The reasoning block can be collapsed and expanded.
- The status bar shows the tokens used against the budget and switches to a warning from 80% of the context.
- A "Moteur simulé" badge is visible on every page.

## US-X1-2 — Switch agents without losing the conversation
> **Update on 2026-11-06:** scenario step **S6**, a wider change, handed to the team ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** 🎭 Simulated. With the real agent, the selector only changes the displayed name: there is no second agent (A2 is not delivered), and the server does not send handoffs.
>
> **Update on 2026-10-24:** 🎭 Still simulated. A2 now exists on the agent side (explorer, developer and reviewer roles and `team_task`, also registered in the web server), but the server does not send handoffs to the interface yet and the selector does not choose a role. Still to connect.
>
> **Update on 2026-10-29:** ◐ Partly real. The server now sends a real `agent_handoff` event when a sub-agent takes over (`delegate_task`, and each relay of `team_task`: explorer → developer → reviewer) and when the main agent takes back control ([ADR-0047](../decisions/0047-real-agent-handoffs-in-the-web.md)); the interface shows them in the conversation and on the Agents page without changing the chosen agent. Still simulated: the "Agent actif" selector only changes the displayed name, because the web server does not read the personas yet (A5, ADR-0042).
>
> **Update on 2026-10-31:** ◐ Unchanged on the server side. The "Agent actif" selector is now **hidden** when the interface is connected to the real server, so it no longer pretends to switch agents; it only remains in the simulated demo. The real relays (`agent_handoff`) are still shown.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): through the API, `delegate_task` streamed the `agent_handoff` relays `main → explorateur → main`.

**As** Camille, the developer who moves from writing to reviewing,
**I want** to activate another agent during the session,
**so that** I keep all the context while changing roles.

**Acceptance criteria:**
- The "Agent actif" selector offers the available agents.
- After a switch, the previous messages stay displayed.
- A "CodeSensei → Relecteur" handoff appears in the conversation and on the Agents page.

## US-X1-3 — Be welcomed before chatting
> **Update on 2026-11-06:** no scenario step: replaced by US-X1-C8 ([traceability](../conception/traceability.md#features-dropped-or-changed-along-the-way)).
> **Status on 2026-10-18:** ✅ Checked with the real agent: the welcome screen, the greeting and the input field that only appears after "Activer la conversation". The displayed status follows the mode ("agent réel (modèle)" or "moteur simulé"). The WebGL fallback and the reduced animations do not depend on the engine and were not checked again.
>
> **Update on 2026-10-31:** Replaced by [US-X1-C8](X1-web-interface.md#us-x1-c8--write-as-soon-as-the-chat-opens-in-a-page-that-uses-the-space): there is no "Activer la conversation" button any more and no 3D scene on the chat welcome screen ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)).

**As** Camille, the developer who opens the chat for the first time,
**I want** the agent to greet me and introduce itself before the conversation is activated,
**so that** I know who I am talking to and can choose when to start.

**Acceptance criteria:**
- The welcome screen shows the agent in the center and a greeting suited to the time of day ("Bonjour", "Bon après-midi", "Bonsoir", "Bonne nuit").
- The input field only appears after a click on "Activer la conversation", or on a suggestion, which starts that scenario directly.
- The "moteur simulé" status is visible from the welcome screen.
- If the browser does not support WebGL, the agent visual is replaced by an animated orb and the welcome screen stays usable.
- Animations are strongly reduced if the user asked for less motion (`prefers-reduced-motion`).

## US-X1-4 — See a polished, sober and whole agent
> **Update on 2026-11-06:** no scenario step: replaced by US-X1-5 to US-X1-7 ([traceability](../conception/traceability.md#features-dropped-or-changed-along-the-way)).
> **Status on 2026-10-18:** Replaced by US-X1-5 to US-X1-7 (see below).


> **Replaced on 2026-10-14 by US-X1-5 to US-X1-7.** After the rehearsal, the welcome screen was judged "bland"; the request
> was an animated world: code being written and its bugs judged, parallax, stop motion. The
> original text is kept below for the record. The 3D scene it describes was removed from the code on
> 2026-11-02 ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 1).
**As** Camille, the developer discovering CodeSensei,
**I want** to see the whole agent, in a polished and calm visual,
**so that** I can focus on the content rather than on effects.

**Acceptance criteria:**
- The agent appears whole in the welcome section, without being cut, whatever the window size; no straight container edge cuts the ribbon, which runs to the edge of the screen.
- The ribbon passes in front of and behind the agent according to its depth; its text scrolls slowly. The agent itself stays still: no tilt, no rotation, no particles, no glitch effect.
- The visual is readable in light theme and in dark theme.
- With "reduce motion" enabled in the system, the ribbon text no longer scrolls.
- If the browser does not support WebGL, an animated orb replaces the visual and the page stays usable.

## US-X1-5 — Understand at a glance what CodeSensei is
> **Update on 2026-11-06:** no scenario step: replaced by US-X1-C9 ([traceability](../conception/traceability.md#features-dropped-or-changed-along-the-way)).
> **Status on 2026-10-18:** ✅ Does not depend on the engine. The pill shows "Connecté à l'agent réel · modèle" when the interface is connected (checked), and "Disponible hors ligne · démo simulée" otherwise.
>
> **Update on 2026-10-31:** Replaced by [US-X1-C9](X1-web-interface.md#us-x1-c9--ask-a-first-question-from-a-calm-full-screen-home-page): the poster with the portrait was removed from the home page ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)).

**As** Camille, the developer who lands on the home page,
**I want** a first page laid out like a poster, with the agent in the center, its name very large, a tagline and a single action button,
**so that** I know right away what the product is and how to try it.

**Acceptance criteria:**
- The agent portrait is in the center, the bust coming out of the bottom of the screen; "CodeSensei" fills the whole width, placed in front of the bust.
- The tagline ("Agent développeur qui pense à voix haute") is a level 1 heading, preceded by a status pill "Disponible hors ligne · démo simulée".
- A short introduction and a "Lancer la démo" button lead to the chat (`/chat`).
- The home page header is a "logo + menu" pill: the menu opens on click, lists all pages, and closes with Escape or a click outside.
- In dark theme, the giant name is white; in light theme, it stays readable on the light background **and** on the dark bust (`difference` blending).
- The action button keeps an AA contrast (white text on `#d63f00`, 4.59:1) in both themes.
- On mobile (375 px), nothing overlaps the text: tagline, portrait with the name, then introduction and button; no horizontal scrolling.

## US-X1-6 — Watch the agent analyze code and judge a bug, live
> **Update on 2026-11-06:** no scenario step: withdrawn ([traceability](../conception/traceability.md#features-dropped-or-changed-along-the-way)).
> **Status on 2026-10-18:** 🎭 Scripted by design: this home page scenery does not show the analysis of the visitor's project, whether the engine is real or simulated.
>
> **Update on 2026-10-31:** Withdrawn. The scripted code scenery (typed snippets, judged bugs, parallax) is no longer on the home page, so the home page shows nothing scripted any more ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)).

**As** Camille, the developer discovering CodeSensei,
**I want** to see the agent write code, scan it, report a bug and then fix it, with scenery that reacts to my mouse,
**so that** I can "dive" into what a code agent does instead of only reading about it.

**Acceptance criteria:**
- An editor types a Python snippet character by character, at a jerky stop-motion pace (one frame every 90 ms, about 11 frames per second).
- A beam runs over the lines; the faulty line turns red, with a wavy underline, along with the verdict (e.g. "✗ L3 · ZeroDivisionError si notes est vide").
- The faulty line is erased and then rewritten fixed, in green, with the result ("✓ correctif appliqué · 3/3 tests verts").
- A terminal shows the steps in parallel (`$ sensai analyse stats.py`, reading, static analysis, verdict, fix) and counts the fixed bugs.
- Three snippets loop: division by zero, `=` instead of `==`, missing `await`.
- When the mouse moves, the code scenery, the portrait, the cards and the name each move according to their depth (parallax).
- A scan beam sweeps across the agent's face, clipped to its silhouette.
- With "reduce motion" enabled in the system, everything is still: the editor directly shows the fixed code, with no parallax and no scrolling.
- The bugs shown are **scripted**: the "Moteur simulé" badge stays visible, and the page does not claim to analyze the visitor's project.
- The code cards are hidden below 1024 px wide or 700 px high, so they never cover the text.

## US-X1-7 — Chat with the agent as in a terminal
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-18:** ✅ Checked in the browser with the real agent: "› Pensée", "$ Action", "← Observation", "✗ Échec", "● en direct", "en cours…" and the collapsible block.

**As** Camille, the developer who uses the chat,
**I want** the conversation to look like my work environment (terminal, colored code),
**so that** I can read the agent's reasoning the way I read a command output.

**Acceptance criteria:**
- The reasoning is shown in a terminal window with numbered lines: "› Pensée", "$ outil(arguments)", "← Observation" in green or "✗ Échec" in red, with the duration in milliseconds.
- While the agent works, the window shows "● en direct", an "en cours…" line carries a blinking cursor, and a sweep runs across the terminal.
- The reasoning block stays collapsible ("Raisonnement · N étapes" button).
- The input area is a command prompt (`~/projet ❯`); it gets an orange frame while the agent is thinking.
- The chat welcome screen shows, on each side of the agent, the editor and the terminal of the live analysis (from 1280 px wide).
- A discreet code rain fills the margins, fades under the conversation and slightly follows the mouse; it does not get in the way of reading the messages.

---

## Part merged from `X1-chat-comfort.md` on 2026-11-02: User stories — [X1] Chat comfort (Markdown, regenerate, stop, conversations, attachments, diff)

Interface: `frontend/`. Added on 2026-10-29, after
comparing the interface with the web interfaces of general-purpose assistants.

Status: ✅ checked with the real agent · ◐ partly · 🎭 simulated · ⏳ not checked yet.
"Checked in a browser" below means a headless Chromium against a local
`sensai-web` with saved conversations and no model (2026-10-29).

---

## US-X1-C1 — Read answers that contain code
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ Rendering checked in a browser on a saved answer (heading, numbered list, Python block coloured with "Copier", link); covered by `frontend/tests/markdown.test.tsx`. Not yet seen while the real model streams.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): in the browser, a Markdown answer with a coloured code block (27 coloured tokens) and "Copier".

**As** Camille, the developer reading the agent's answer,
**I want** headings, lists, links and coloured code blocks I can copy in one click,
**so that** I can use the code without selecting it by hand.

**Acceptance criteria:**
- Headings, bullet and numbered lists, quotes, bold, italic and inline code are rendered.
- Each code block shows its language and a "Copier" button that copies the raw code.
- Only `http(s)` links are clickable and open in a new tab; HTML written by the model stays text.

## US-X1-C2 — Ask again or stop
> **Update on 2026-11-06:** scenario step **S8**, memory and a long session ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ Covered by `frontend/tests/regenerate.test.tsx` and `chat.test.tsx`; the "↻ Régénérer" button was seen in a browser. Not yet tried with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): "↻ Régénérer" showed a second answer in the browser; through the API, `/again` gave a new answer without the cache.

**As** Camille, the developer unhappy with an answer, or who sees the agent going the wrong way,
**I want** to regenerate the last answer, or stop it with Escape,
**so that** I don't have to retype my question or wait for a useless answer.

**Acceptance criteria:**
- "↻ Régénérer" appears under the last finished answer only.
- With the server it sends `/again`, which skips the answer cache; the question is shown again.
- Escape in the message field stops the answer being generated, like "■ Arrêter".

## US-X1-C3 — Keep several conversations side by side
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ Checked in a browser (list, current conversation highlighted, reopen); delete and new conversation covered by `frontend/tests/conversations.test.tsx` and `tests/web/test_server.py`.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): a conversation was listed, reloaded and continued through the API (the agent remembered the function discussed) and reopened from the sidebar in the browser.

**As** Camille, the developer working on several subjects,
**I want** the list of my conversations next to the chat, to start, reopen or delete one,
**so that** I don't mix subjects or go through another page.

**Acceptance criteria:**
- The sidebar lists the project's conversations and highlights the open one.
- "+ Nouvelle conversation" starts an empty one; the next message creates it on the server.
- Deleting asks for confirmation in the line; it is refused while an answer is being generated.

## US-X1-C4 — Show a file to the agent
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ Covered by `frontend/tests/attachments.test.tsx`; not yet tried with the real model.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): a message with a fenced `outils.py` got the function explained.

**As** Camille, the developer with a file outside the project,
**I want** to attach it with the paperclip or by dropping it on the message field,
**so that** the agent reads it without me pasting it.

**Acceptance criteria:**
- Text files only (code, Markdown, JSON…), at most 3 per message; others are refused with a message.
- The content is sent in a code block after the question; a message over 20,000 characters is blocked before sending.

## US-X1-C5 — See exactly what a file write changes
> **Update on 2026-11-06:** scenario step **S4**, the fix, approved ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ Covered by `frontend/tests/cards.test.tsx`; the diff itself is computed by the server (`write_file`), already tested. Not yet seen with the real agent.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): `write_file` showed a coloured diff (one added line in green), and "Autoriser" changed the file.

**As** Camille, the developer asked to allow a file write,
**I want** to see the change as a coloured diff,
**so that** I allow or refuse knowing what will change.

**Acceptance criteria:**
- Added lines are green, removed lines red, `@@` markers highlighted.
- A request without a diff (creation, other tools) stays plain text.

## US-X1-C6 — Find every page and conversation in one left sidebar
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-29:** ◐ `frontend/src/ui/Sidebar.tsx`, covered by `frontend/tests/sidebar.test.tsx`. Not yet seen in a browser with the real model.
>
> **Update on 2026-10-31:** ✅ Seen in a browser against a real `sensai-web` through the Vite proxy, with the only local model, `granite3.1-moe` (3.3B, `--no-rag`); not yet with `qwen3-coder:30b`: the sidebar listed the real conversations, reopened one, and the badge showed the real agent.

> **Update on 2026-11-01:** ✅ Checked with `qwen3-coder:30b` ([trial](../performance/essais/essai-2026-11-01.md)): the left sidebar showed 9 tabs and 14 conversations; at 390 px the menu drawer closed with Escape.

**As** Camille, the developer who moves between the chat and the other pages,
**I want** all tabs and conversations in one left sidebar, like the web interfaces of general-purpose assistants,
**so that** I switch page or conversation in one click without losing my place.

**Acceptance criteria:**
- The sidebar lists the conversations and every tab: Accueil, Chat, Mémoire, Agents, Qualité, Prompts, Journal, Planification, Export; the current one is highlighted.
- The engine badge ("Moteur simulé" or the real server) and the theme toggle sit at the bottom of the sidebar.
- On small screens the sidebar is a drawer opened and closed by a menu button ("Ouvrir le menu" / "Fermer le menu"); it closes on Escape, on a click outside it and after choosing a page.

## US-X1-C7 — See that the agent is working, without the page jumping around
> **Update on 2026-11-06:** scenario step **S3**, the invoice report bug ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-31:** ◐ ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)): `frontend/src/features/chat/ThinkingIndicator.tsx`, `ReasoningRibbon.tsx`, `MessageList.tsx`, covered by `frontend/tests/cards.test.tsx`. Checked in a browser with the simulated engine; not yet with the real model.
>
> **Update on 2026-10-31:** ✅ Seen against a real `sensai-web` through the Vite proxy, with the only local model, `granite3.1-moe` (3.3B, `--no-rag`); not yet with `qwen3-coder:30b`: indicator with the elapsed seconds during the turn, reasoning block folded at the end, and an immediate follow-up question accepted (no 409, since a turn now ends when the server closes the stream).

**As** Camille, the developer who waits for an answer,
**I want** one calm, clear signal that the agent is working, and a page that does not move by itself,
**so that** I know it is busy and for how long, and I can read earlier messages in peace.

**Acceptance criteria:**
- While a turn runs, a status line shows a rotating star, what the agent does ("Réflexion", "Utilise <outil>", "Rédaction") and the seconds elapsed.
- The reasoning block stays open during the turn, then folds by itself when the answer is finished and shows "Raisonnement · N étapes · X s"; one click opens it again.
- No animation jerks: no shaking avatar, no sweeping light; with "reduce motion" set in the system, nothing moves.
- If I scroll up during an answer, the page stays where I am and a "↓ Revenir en bas" button appears.

## US-X1-C8 — Write as soon as the chat opens, in a page that uses the space
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-31:** ◐ ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)): `frontend/src/features/chat/Welcome.tsx`, `frontend/src/pages/Chat.tsx`, covered by `frontend/tests/welcome.test.tsx`, `chat.test.tsx` and `panels.test.tsx`. Checked in a browser at 1440×900 and 375×812 with the simulated engine.
>
> **Update on 2026-10-31:** ✅ Seen against a real `sensai-web` through the Vite proxy, with the only local model, `granite3.1-moe` (3.3B, `--no-rag`); not yet with `qwen3-coder:30b`: first question typed on the welcome screen, streamed answer, input docked at the bottom.

**As** Camille, the developer who opens the chat to ask something,
**I want** the input field ready and focused on the welcome screen, and a conversation that uses the width of my screen,
**so that** I start without an extra click and read long answers without a narrow column.

**Acceptance criteria:**
- The welcome screen shows a greeting, the focused input field and the suggestions; there is no "Activer la conversation" button.
- The conversation column is up to 56rem wide; the input sticks to the bottom of the screen and shows the context gauge under it.
- The Artefact / Sources panel is folded by default, opened by an "Artefact · Sources" button with a dot when there is new content; my choice is remembered; on a phone it opens as a drawer.

## US-X1-C9 — Ask a first question from a calm, full-screen home page
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-31:** ✅ ([ADR-0051](../decisions/0051-calm-chat-layout-and-motion.md)): `frontend/src/features/hero/LandingHero.tsx`, covered by `frontend/tests/landing.test.tsx`. Checked in a browser at 1440×900 and 375×812, light and dark themes; a question typed on the home page was answered by the real `sensai-web` through the Vite proxy, with the only local model, `granite3.1-moe` (3.3B, `--no-rag`); not yet with `qwen3-coder:30b`.

**As** Camille, the developer who opens CodeSensei,
**I want** a home page with only the name, one question field and two buttons,
**so that** I understand where to start without being overwhelmed, and ask my question at once.

**Acceptance criteria:**
- The home page fills the screen: "CodeSensei" very large and translucent, one rounded question field over it, a warm halo of light on the right, a sentence and the "Lancer la démo" / "Ouvrir le chat" and "28 fonctionnalités" buttons at the bottom.
- A question typed in the field (Enter or the arrow button) is sent to the agent and opens the chat.
- A small label says whether the real agent (with its model) or the simulated demo answers.
- No image and no scripted animation; only the halo breathes slowly, and it stays still with "reduce motion" set in the system.
- The page follows the light and dark themes and has no horizontal scrolling at 375 px.

## US-X1-C10 — Reach the real agent without configuring anything
> **Update on 2026-11-06:** scenario step **S1**, Camille resumes Friday's work ([scenario](../conception/persona-and-scenario.md#the-day-camille-fixes-the-invoice-report)).
> **Status on 2026-10-31:** ✅ `frontend/vite.config.ts` (proxy), `frontend/src/state/connection.tsx` (retry every 3 s, for 5 minutes at most), covered by `frontend/tests/connection.test.tsx`. Checked in a browser: with `npm run dev` and `sensai-web` started **after** the page, the page asked for the token within seconds and then talked to the real agent.

**As** Marc, the lead who sets the interface up while adjusting the server,
**I want** the interface to find `sensai-web` on its own, even if I start the server after opening the page,
**so that** I test with the real agent instead of being left on the demo.

**Acceptance criteria:**
- With `npm run dev`, calls to `/api` and `/share` go to `sensai-web` (port 8000, or `SENSAI_API`).
- While the page is in demo mode because no server answered, it checks again every 3 seconds, for 5 minutes at most (reload the page to search again); as soon as the server answers, it asks for the access token (or reuses the saved one).
- Without any server, the simulated demo keeps working and says so.

---

## Code audit on 2026-11-01

Each story checked against the code and the automated tests (not against earlier statuses). ✅ implemented: every criterion has code and a test that proves it · ◐ partial: what is missing is named · ✗ not implemented. Checks with the real model are separate and listed in the statuses above. Paths are under `src/sensai/` unless they start with `tests/`, `frontend/` or `scripts/`.

| Story | Status | Code | Test | Missing / note |
| --- | --- | --- | --- | --- |
| US-X1-1 | ◐ | `frontend/src/features/chat/`, `web/runtime.py` (`usage`) | `tests/web/test_real_features.py`, `frontend/tests/realFeatures.test.tsx` | The token bar is now fed by `usage`, but the counts are estimates (characters / 4) |
| US-X1-2 | ◐ | `frontend/src/pages/Agents.tsx` | `tests/web/test_handoffs.py` | Real hand-offs are shown (ADR-0047); the "Agent actif" selector sets the persona, it does not switch to another agent |
| US-X1-3 | ✅ | `frontend/src/features/chat/Welcome.tsx` | `frontend/tests/welcome.test.tsx` |  |
| US-X1-4 | — | — | — | Replaced by US-X1-5 to US-X1-7 |
| US-X1-5 | ✅ | `frontend/src/features/hero/LandingHero.tsx` | `frontend/tests/landing.test.tsx` |  |
| US-X1-6 | — | — | — | Withdrawn on 2026-11-02 with the decorative layer ([ADR-0056](../decisions/0056-scope-review-features-to-drop-or-limit.md), item 1): the animated code scenery is removed from the code |
| US-X1-7 | ✅ | `frontend/src/features/chat/ReasoningRibbon.tsx` | `frontend/tests/cards.test.tsx`, `frontend/tests/chat.test.tsx` |  |
| US-X1-C1 | ✅ | `frontend/src/features/chat/markdown.tsx` | `frontend/tests/markdown.test.tsx` |  |
| US-X1-C2 | ✅ | `frontend/src/features/chat/` | `frontend/tests/regenerate.test.tsx`, `frontend/tests/chat.test.tsx` |  |
| US-X1-C3 | ✅ | `frontend/src/features/chat/ConversationList.tsx`, `web/server.py` | `frontend/tests/conversations.test.tsx`, `tests/web/test_server.py` |  |
| US-X1-C4 | ✅ | `frontend/src/features/chat/attachments.ts` | `frontend/tests/attachments.test.tsx` |  |
| US-X1-C5 | ✅ | `tools/write_file_tool.py`, `frontend/src/features/chat/ActionCards.tsx` | `frontend/tests/cards.test.tsx`, `frontend/tests/diff.test.ts` |  |
| US-X1-C6 | ✅ | `frontend/src/ui/Sidebar.tsx` | `frontend/tests/sidebar.test.tsx` |  |
| US-X1-C7 | ✅ | `frontend/src/features/chat/ThinkingIndicator.tsx` | `frontend/tests/cards.test.tsx` |  |
| US-X1-C8 | ✅ | `frontend/src/features/chat/Welcome.tsx`, `frontend/src/pages/Chat.tsx` | `frontend/tests/welcome.test.tsx`, `frontend/tests/panels.test.tsx` |  |
| US-X1-C9 | ✅ | `frontend/src/features/hero/LandingHero.tsx` | `frontend/tests/landing.test.tsx` |  |
| US-X1-C10 | ✅ | `frontend/vite.config.ts`, `frontend/src/state/connection.tsx` | `frontend/tests/connection.test.tsx` |  |
