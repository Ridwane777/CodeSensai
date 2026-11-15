# ADR-0025 - Home hero laid out like a poster, without a 3D scene

- **Status**: Accepted (2026-11-01, approved by the team)
- **Date**: 2026-10-14
- **Deciders**: Christopher (Workstream D)
- **Workstream**: D

## Context
Expected behavior: [US-X1-5](../user-stories/README.md), which replaces US-X1-4 for the home page.

Christopher provided a reference mockup for the home hero: a portrait in the center, a very large name
across the bottom of the screen placed in front of the figure, a tagline on the left, a short
introduction and an orange button on the right, and a menu reduced to a "logo + burger" pill in the top left.
He wants this rendering "exactly", adapted to light and dark themes, with every element properly highlighted.

ADR-0021 displayed the portrait in a three.js scene surrounded by ribbons. That visual does not match
the mockup (which has no ribbon), and ADR-0021 already set its own revision threshold: "if the weight of
three.js is no longer justified, replace the scene with an image and CSS".

## Considered options
| Option | Pros | Cons |
| --- | --- | --- |
| Keep the 3D scene and put the new layout around it | Nothing to remove; ribbon kept | The ribbon clutters the giant name and the tagline; 808 KB of three.js loaded for a static image; far from the mockup. |
| **Portrait as an image (`<img>`), CSS layout, framer-motion animations** | Faithful to the mockup; no more three.js chunk on the home page; no WebGL required | The ribbon disappears from the home page; the chat welcome screen keeps the 3D scene, so the same portrait gets two treatments. |
| Pre-composed image (portrait + name in one file) | Identical rendering everywhere | Text not selectable, not translatable, blurry at large sizes; impossible to adapt the name to the theme. |

## Decision
The home hero (`frontend/src/features/hero/LandingHero.tsx`) displays the portrait as an `<img>`, centered,
with the bust coming up from the bottom. The name "CodeSensai" spans the full width (size in `vw`) and sits in front of
the bust. In dark theme it is white, as in the mockup. In light theme it is rendered with
`mix-blend-mode: difference`: dark on the light background, light where it crosses the dark bust, so readable
everywhere without picking a single color. The home header becomes a floating pill (logo + burger
menu); other pages keep the full navigation bar. The call-to-action button uses
`#d63f00` with white text in both themes (contrast 4.59:1, AA). On mobile, the grid collapses
and the elements stack: tagline, portrait with the name overlaid, introduction and button.

The 3D scene from ADR-0021 is still used by the chat welcome screen (`Welcome`).

## Consequences
- ✅ Rendering faithful to the mockup in both themes, checked by eye in the browser at 1440×900,
  1024×768 and 375×812 (no horizontal scrolling).
- ✅ The home page no longer loads the scene chunk (808 KB, 218 KB compressed, measured on the
  2026-10-14 build): it is only downloaded when opening the chat. The portrait (111 KB) is enough.
- ✅ The home page no longer needs WebGL.
- ❌ **The ribbon disappears from the home page**: the home and chat visuals are no longer treated the same way.
- ❌ **The `difference` blend in light theme** gives the name a cream tint where it crosses the blue
  bust, and a bluish tint over the orange visor: this is intentional (poster effect), but it is not a solid black.
- ❌ **The name size is tuned by hand** (`17.8vw`) for the Plus Jakarta Sans font: if the font does not
  load, the fallback font is narrower and the name no longer fills the full width. If the name
  changes, this value must be retuned.
- ❌ The home menu hides navigation behind one more click than on other pages.
- ❌ The rights to the portrait are still not verified (see ADR-0021): the hero puts it even more
  in the spotlight.
- Follow-up: tests `frontend/tests/landing.test.tsx` (floating menu, title, call to action). Revisit if
  the team wants the ribbon back on the home page, or if the product name changes.
