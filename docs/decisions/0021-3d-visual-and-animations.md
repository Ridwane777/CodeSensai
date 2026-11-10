# ADR-0021 — Agent visual: the supplied portrait, static, with a subtle glow and ribbon

- **Status**: Superseded by ADR-0056 (2026-11-02: the 3D visual is removed from the code)
- **Date**: 2026-10-13
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D

## Context
The landing page and the chat welcome screen must show an agent with a polished visual. Christopher supplied
the portrait of the chosen AI (high-resolution PNG with an alpha channel). Its visor carries the text
"TURNOVER MARKETING", the name of a third-party brand, and its origin and rights have not been checked.

Several versions were tried and then rejected by Christopher: a 3D head built in code or
taken from a licensed scan (it did not look like the intended AI), a crossfade between 8 views of a sheet
(blurry, artificial look), then a heavily animated version (tilt toward the cursor, electrons, bursts,
mood cycle), judged "too much". He wants something simple and well drawn.

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| 3D head built in code or licensed scan | Real 3D, clear rights | Does not look like the intended AI (rejected). |
| Rotation by crossfading between the views of a sheet | Full turn | Small, blurry views, artificial look (rejected). |
| Animated portrait (tilt, electrons, bursts, cycle) | Spectacular | Judged excessive by the requester (rejected). |
| **Static portrait, soft glow, ribbon around it** | Sober, sharp, faithful to the supplied image; the ribbon passes in front of and behind the AI thanks to depth | The AI is a static image: see the drawbacks. |

## Decision
A script (`frontend/scripts/prepare_ai_frames.py`) cuts out the portrait and writes it as WebP
(`frontend/public/ai/portrait.webp`). The scene (three.js) shows this static portrait, a soft orange glow
and two thin ribbons around it, in front and behind; only the ribbon text scrolls slowly. There is
no other animation.

**The scene is not boxed in a container**: the canvas covers the full screen width, behind
the text. Its height follows the window's and everything is scaled to it, placed on the right (or
centered on small screens): the AI stays whole and the ribbon runs to the screen edge instead of being
cut by a straight line. On the chat welcome screen, the canvas also overflows its slot by 12 % at the top and
bottom, so the ribbon is not truncated, and the AI is centered on the page there. If WebGL
is missing, an animated orb takes its place. `framer-motion` animates the rest
of the interface (entrances, counters) and respects `prefers-reduced-motion`; in that case the ribbon
text no longer scrolls.

## Consequences
- ✅ A sober, sharp visual, whole in the hero section, in light and dark theme alike.
- ✅ Nothing is cut by a container edge, and the scaling follows the screen.
- ✅ The rest of the site is not weighed down: the scene is a separate chunk, loaded on demand.
- ❌ **Rights not checked**: the image's origin and the right to reuse it are not established (`docs/legal/licenses.md`). It carried a third-party brand name; the script **erases this text** by default (`--keep-text` keeps it). This is a modification of the work: to be confirmed before any public release.
- ❌ **The AI is a static image**: no tilt, rotation or depth. The ribbon, however, is real 3D.
- ❌ **Erasing the text leaves a slightly uneven look** on the visor, visible up close.
- ❌ **Measured weight (build of 2026-10-13)**: scene chunk 808 KB (218 KB compressed), image 111 KB, versus 321 KB (106 KB compressed) for the main bundle, `framer-motion` included. That is heavy for an almost static visual: most of the chunk is three.js. The fallback orb shows during loading.
- ❌ **The scene redraws continuously** to scroll the ribbon text, and a full-width canvas costs more than a small frame on a large high-pixel-density screen (rendering capped at twice the density, not measured on the demo machine). Horizontal page scrolling must also be hidden.
- ❌ **WebGL is required**; the rendering is not covered by automated tests (only WebGL detection, the fallback and the greeting are). It is checked by eye in the browser.
- ❌ **The source image** (a PNG) is at the repository root, not tracked by git: without it, the script cannot be replayed.
- Follow-up: confirm the image's origin and rights; if the team wants its own name on the visor, regenerate the image with that text rather than retouching it; measure display on the demo machine. **Revision threshold**: if the weight of three.js is no longer justified (for example if the ribbon becomes a plain image), replace the scene with an image and CSS, and drop the dependency. Same decision if the scene takes more than a few seconds to display on the demo machine.
