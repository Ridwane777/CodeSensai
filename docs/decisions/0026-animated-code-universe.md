# ADR-0026 — Animated "code" universe: stop motion, parallax and live bug analysis

- **Status**: Superseded by ADR-0056 (2026-11-02: the animated code universe was removed from the code)
- **Date**: 2026-10-14
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D

## Context
Expected behavior: [US-X1-6 and US-X1-7](../user-stories/README.md), written before this decision was finalized; they replace US-X1-4 ("calm visual, no particles").

After the poster hero (ADR-0025), Christopher finds the home page "bland, no animation". He wants visitors to
"dive into the universe" of a coding agent: code being typed in the hero, analyzed, with its
bugs judged, a simple stop-motion animation, parallax and effects that follow the mouse.
He also wants the chat to adopt the same universe.

ADR-0021 notes that a heavily animated version (tilt, electrons, bursts) had been judged "too much".
The current request is about something else: showing the agent's **work** (read, scan, judge,
fix), not scenery that moves for the sake of moving.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Video or GIF of a recorded session | Exact rendering of a real session | Heavy, blurry at large sizes, impossible to adapt to the theme, text not accessible. |
| Lottie / dedicated animation library | Rich animations | New dependency, and the animation is drawn in another tool. |
| **React components + CSS `steps()` + framer-motion (already present)** | No added dependency; real text, colored per theme; testable logic | Everything must be written and tuned by hand. |

## Decision
A small module `frontend/src/features/code/` carries the universe:
- `useAnalysis`: a state machine (typing → scan → bug → erase → fix → verdict) that
  advances one frame every 90 ms, about 11 frames/s, the choppy rhythm of stop motion. Three realistic
  Python snippets loop (division by zero, `=` instead of `==`, missing `await`).
- `CodeEditorCard` and `VerdictCard`: the editor where the code is typed, with the scan beam, the faulty
  line underlined in red then rewritten in green, and the terminal that "judges" and counts fixed bugs.
- `CodeRain`: columns of code scrolling in jerks (`animation: … steps(48)`), as scenery.
- `useMouseParallax`: the mouse moves each layer according to its depth (scenery, portrait, cards, name).
- A frame-by-frame jitter (`.boil`) on the cards, and a beam sweeping across the AI's face,
  clipped to its silhouette by a CSS mask.

The chat reuses the universe: code rain in the background, reasoning presented as a numbered terminal
("› Thought", "$ tool(args)", "← Observation"), a `~/project ❯` prompt, and the live analysis on
its welcome screen.

If the user asks for reduced motion (`prefers-reduced-motion`), everything stops: the editor shows
the fixed code directly, parallax stays at zero, the scenery is still.

## Consequences
- ✅ The home page shows what the agent does (read, analyze, judge, fix) instead of just announcing it.
- ✅ No added dependency: the main bundle goes from 324 KB to 335 KB (107 → 111 KB compressed,
  measured on the 2026-10-14 build).
- ✅ The analysis loop is tested (`frontend/tests/analysis.test.ts`); the rest is checked by eye.
- ❌ **The bugs shown are scripted**: it is a staged scene, not a real analysis of the project. The
  demo must say so (the "simulated engine" badge stays visible).
- ❌ **More continuous work for the browser**: a timer every 90 ms and permanent CSS
  animations. Not measured on the demo machine.
- ❌ **Risk of overload**: this is precisely what a previous version was criticized for
  (ADR-0021). If the team finds the whole thing too busy, remove the `.boil` jitter first, then the
  code rain.
- ❌ The hero code cards are hidden below 1024 px wide or 700 px tall, for lack of space.
- Follow-up: measure CPU usage on the demo machine; replace the scripted snippets with
  real results once the real engine (`httpEngine`) is wired in.
